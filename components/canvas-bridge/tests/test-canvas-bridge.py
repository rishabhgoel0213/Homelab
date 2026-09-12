import importlib.util
import json
import os
import sys
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(
    os.environ.get(
        "CANVAS_BRIDGE_SCRIPT",
        Path(__file__).parent.parent / "scripts" / "canvas-bridge.py",
    )
)
if not MODULE_PATH.exists():
    MODULE_PATH = Path(__file__).with_name("canvas_bridge.py")


def load_bridge(state_dir: str):
    os.environ["CANVAS_BRIDGE_STATE_DIR"] = state_dir
    spec = importlib.util.spec_from_file_location("canvas_bridge_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CanvasBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = load_bridge(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_oauth_callback_requires_code_and_preserves_state(self):
        code, state = self.bridge.parse_oauth_callback(
            "https://umd.instructure.com/login/oauth2/auth?code=abc123&state=state456"
        )
        self.assertEqual("abc123", code)
        self.assertEqual("state456", state)

        code, state = self.bridge.parse_oauth_callback(
            "https://sso.canvaslms.com/canvas/login?code=abc123&amp;state=state456"
        )
        self.assertEqual("abc123", code)
        self.assertEqual("state456", state)

    def test_authorization_uses_registered_mobile_callback(self):
        with self.bridge.db_session() as db:
            client = self.bridge.CanvasClient(db)
            with mock.patch.object(
                self.bridge.CanvasClient,
                "mobile_credentials",
                return_value=("public-client", "mobile-secret", "https://umd.instructure.com"),
            ):
                url, state = client.begin_oauth()
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            pending = db.execute("SELECT COUNT(*) FROM pending_oauth").fetchone()[0]
        self.assertEqual(
            ["https://sso.canvaslms.com/canvas/login"],
            query["redirect_uri"],
        )
        self.assertEqual(["code"], query["response_type"])
        self.assertEqual([state], query["state"])
        self.assertEqual(1, pending)
        self.assertEqual("urn:ietf:wg:oauth:2.0:oob", self.bridge.TOKEN_REDIRECT_URI)

    def test_html_to_text_removes_active_content(self):
        value = self.bridge.html_to_text(
            "<h1>Week 1</h1><script>steal()</script><p>Read <strong>chapter 2</strong>.</p>"
        )
        self.assertEqual("Week 1\n\nRead chapter 2.", value)
        self.assertNotIn("steal", value)

    def test_html_to_text_preserves_safe_links_without_secret_parameters(self):
        value = self.bridge.html_to_text(
            '<p><a href="https://example.test/setup?token=secret&amp;pwd=meeting-secret&amp;week=1">Setup guide</a></p>'
            '<p><a href="javascript:alert(1)">Unsafe</a></p>'
        )
        self.assertEqual("Setup guide (https://example.test/setup?week=1)\n\nUnsafe", value)
        self.assertNotIn("secret", value)
        self.assertNotIn("pwd", value)
        self.assertNotIn("javascript", value)

    def test_canvas_page_urls_only_returns_same_course_pages(self):
        value = (
            '<a href="/courses/10/pages/setup-guide">Setup</a>'
            '<a href="https://umd.instructure.com/courses/10/pages/lab-1?module_item_id=4">Lab</a>'
            '<a href="/courses/11/pages/private">Other course</a>'
        )
        self.assertEqual(
            {"setup-guide", "lab-1"},
            self.bridge.canvas_page_urls_from_html(value, "10"),
        )

    def test_wiki_front_page_and_linked_course_page_are_mirrored_without_modules(self):
        with self.bridge.db_session() as db:
            db.execute(
                """
                INSERT INTO courses(id, name, active, json, synced_at)
                VALUES('10', 'CMSC 216', 1, '{}', '2026-01-01T00:00:00+00:00')
                """
            )
            engine = self.bridge.SyncEngine(db)

            def paginated(path):
                if "/modules?" in path or "/assignments?" in path or path.startswith("/api/v1/announcements?"):
                    return []
                self.fail(f"Unexpected paginated request: {path}")

            def api_json(path):
                if path == "/api/v1/courses/10/front_page":
                    return (
                        {
                            "url": "home",
                            "title": "Course Home",
                            "body": (
                                '<p><a href="/courses/10/pages/setup-guide">Setup guide</a></p>'
                                '<p><a href="https://example.test/resources">Resources</a></p>'
                            ),
                            "html_url": "https://umd.instructure.com/courses/10/pages/home",
                            "updated_at": "2026-08-30T00:00:00Z",
                            "front_page": True,
                        },
                        mock.Mock(),
                    )
                if path == "/api/v1/courses/10/pages/setup-guide":
                    return (
                        {
                            "url": "setup-guide",
                            "title": "Setup Guide",
                            "body": "<p>Install the compiler.</p>",
                            "html_url": "https://umd.instructure.com/courses/10/pages/setup-guide",
                            "updated_at": "2026-08-30T00:00:00Z",
                            "front_page": False,
                        },
                        mock.Mock(),
                    )
                self.fail(f"Unexpected API request: {path}")

            with mock.patch.object(engine.canvas, "paginated", side_effect=paginated):
                with mock.patch.object(engine.canvas, "api_json", side_effect=api_json):
                    counts = engine._sync_course("10", {"default_view": "wiki"})
            db.commit()
            documents = self.bridge.list_documents(db, course_id="10", kind="page")
            home = self.bridge.get_document(db, "10", "page", "home")

        self.assertEqual(2, counts["documents"])
        self.assertEqual({"Course Home", "Setup Guide"}, {item["title"] for item in documents})
        self.assertTrue(next(item for item in documents if item["title"] == "Course Home")["front_page"])
        self.assertIn("Setup guide (/courses/10/pages/setup-guide)", home["body"])
        self.assertIn("Resources (https://example.test/resources)", home["body"])

    def test_pairing_code_is_single_use(self):
        with self.bridge.db_session() as db:
            security = self.bridge.WebSecurity(db)
            code = security.create_pairing_code()
            self.assertRegex(code, r"^[0-9]{6}$")
            self.assertTrue(security.consume_pairing_code(code))
            self.assertFalse(security.consume_pairing_code(code))

    def test_web_session_is_signed(self):
        with self.bridge.db_session() as db:
            security = self.bridge.WebSecurity(db)
            cookie = security.issue_session()
            session = security.validate_session(cookie)
            self.assertIsNotNone(session)
            self.assertIsNone(security.validate_session(cookie + "tampered"))
            csrf = security.csrf(session)
            self.assertTrue(security.verify_csrf(session, csrf))
            self.assertFalse(security.verify_csrf(session, csrf + "0"))

    def test_course_outline_tracks_instructor_order(self):
        with self.bridge.db_session() as db:
            db.execute(
                """
                INSERT INTO courses(id, name, active, json, synced_at)
                VALUES('10', 'PHYS 123', 1, '{}', '2026-01-01T00:00:00+00:00')
                """
            )
            db.executemany(
                """
                INSERT INTO modules(id, course_id, name, position, json, synced_at)
                VALUES(?, '10', ?, ?, '{}', '2026-01-01T00:00:00+00:00')
                """,
                [("m2", "Second", 2), ("m1", "First", 1)],
            )
            db.executemany(
                """
                INSERT INTO module_items(
                    id, course_id, module_id, title, type, position, json, synced_at
                ) VALUES(?, '10', ?, ?, 'Page', ?, '{}', '2026-01-01T00:00:00+00:00')
                """,
                [("i2", "m1", "Later item", 2), ("i1", "m1", "First item", 1)],
            )
            db.commit()
            outline = self.bridge.course_outline(db, "10")
        self.assertEqual(["First", "Second"], [item["name"] for item in outline["modules"]])
        self.assertEqual(["First item", "Later item"], [item["title"] for item in outline["modules"][0]["items"]])

    def test_search_is_scoped_to_selected_course(self):
        with self.bridge.db_session() as db:
            for course_id, name in [("1", "Mechanics"), ("2", "Biology")]:
                db.execute(
                    """
                    INSERT INTO courses(id, name, active, json, synced_at)
                    VALUES(?, ?, 1, '{}', '2026-01-01T00:00:00+00:00')
                    """,
                    (course_id, name),
                )
            for course_id, title in [("1", "Angular momentum"), ("2", "Cell momentum")]:
                db.execute(
                    """
                    INSERT INTO documents(
                        kind, course_id, object_id, title, body, metadata_json, synced_at
                    ) VALUES('page', ?, ?, ?, 'momentum notes', '{}', '2026-01-01T00:00:00+00:00')
                    """,
                    (course_id, f"d{course_id}", title),
                )
            db.commit()
            results = self.bridge.search_materials(db, "momentum", course_id="1")
        self.assertEqual(1, len(results))
        self.assertEqual("Mechanics", results[0]["course_name"])

    def test_mobile_credentials_never_need_to_be_persisted(self):
        payload = {
            "authorized": True,
            "result": 0,
            "client_id": "public-client",
            "client_secret": "mobile-secret",
            "base_url": "https://umd.instructure.com/",
        }
        with mock.patch.object(
            self.bridge.SafeHTTPClient,
            "json",
            return_value=(payload, mock.Mock()),
        ):
            client_id, client_secret, base_url = self.bridge.CanvasClient.mobile_credentials()
        self.assertEqual(("public-client", "mobile-secret", "https://umd.instructure.com"), (client_id, client_secret, base_url))
        with self.bridge.db_session() as db:
            persisted = json.dumps([dict(row) for row in db.execute("SELECT * FROM settings")])
        self.assertNotIn("mobile-secret", persisted)

    def test_connection_status_contains_no_tokens(self):
        with self.bridge.db_session() as db:
            db.execute(
                """
                INSERT INTO auth(
                    singleton, canvas_url, access_token, refresh_token, user_json,
                    connected_at, updated_at
                ) VALUES(1, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "https://umd.instructure.com",
                    "access-secret",
                    "refresh-secret",
                    '{"id": 7, "name": "Student"}',
                    "2026-01-01T00:00:00+00:00",
                    "2026-01-01T00:00:00+00:00",
                ),
            )
            db.commit()
            status = self.bridge.connection_status(db)
        rendered = json.dumps(status)
        self.assertNotIn("access-secret", rendered)
        self.assertNotIn("refresh-secret", rendered)
        self.assertTrue(status["connected"])

    def test_running_sync_ui_labels_transient_counts_and_disables_sync(self):
        body = self.bridge.render_connected_home(
            {
                "connected": True,
                "user": {"name": "Student"},
                "counts": {"active_courses": 6, "modules": 71, "documents": 843},
                "sync": {
                    "state": "running",
                    "started_at": "2026-07-26T02:06:26+00:00",
                    "completed_at": None,
                    "error": None,
                    "summary": None,
                },
            },
            "csrf-value",
        )
        self.assertIn("Sync in progress", body)
        self.assertIn("active courses (updating)", body)
        self.assertIn("may be temporarily incomplete", body)
        self.assertIn("disabled", body)
        self.assertNotIn("No completed sync yet", body)
        self.assertNotIn("Last successful sync", body)

    def test_completed_sync_ui_uses_completed_wording_and_enables_sync(self):
        body = self.bridge.render_connected_home(
            {
                "connected": True,
                "user": {"name": "Student"},
                "counts": {"active_courses": 14, "modules": 71, "documents": 843},
                "sync": {
                    "state": "idle",
                    "started_at": "2026-07-26T02:06:26+00:00",
                    "completed_at": "2026-07-26T02:13:42+00:00",
                    "error": None,
                    "summary": {"courses": 14},
                },
            },
            "csrf-value",
        )
        self.assertIn("Last sync completed", body)
        self.assertIn("Sync now", body)
        self.assertNotIn("active courses (updating)", body)
        self.assertNotIn("disabled", body)

    def test_failed_sync_ui_does_not_call_failure_a_success(self):
        body = self.bridge.render_connected_home(
            {
                "connected": True,
                "user": {"name": "Student"},
                "counts": {"active_courses": 14, "modules": 71, "documents": 843},
                "sync": {
                    "state": "error",
                    "started_at": "2026-07-26T02:06:26+00:00",
                    "completed_at": "2026-07-26T02:07:00+00:00",
                    "error": "Connection reset by peer",
                    "summary": None,
                },
            },
            "csrf-value",
        )
        self.assertIn("Last sync failed", body)
        self.assertIn("Connection reset by peer", body)
        self.assertIn("Retry sync", body)
        self.assertNotIn("Last successful sync", body)

    def test_cross_host_redirect_drops_bearer_token(self):
        request = urllib.request.Request(
            "https://umd.instructure.com/api/v1/courses",
            headers={"Authorization": "Bearer secret"},
        )
        redirected = self.bridge.SafeRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://example.invalid/download",
        )
        self.assertIsNotNone(redirected)
        self.assertIsNone(redirected.get_header("Authorization"))

    def test_routing_mark_is_applied_before_connect(self):
        connection = mock.Mock()
        address = (self.bridge.socket.AF_INET, self.bridge.socket.SOCK_STREAM, 6, "", ("192.0.2.1", 443))
        with mock.patch.object(self.bridge.socket, "getaddrinfo", return_value=[address]):
            with mock.patch.object(self.bridge.socket, "socket", return_value=connection):
                with mock.patch.object(self.bridge, "SOCKET_MARK", 0x80000):
                    result = self.bridge.marked_create_connection(("example.test", 443), timeout=10)
        self.assertIs(connection, result)
        self.assertEqual(
            [
                mock.call.settimeout(10),
                mock.call.setsockopt(
                    self.bridge.socket.SOL_SOCKET,
                    self.bridge.socket.SO_MARK,
                    0x80000,
                ),
                mock.call.connect(("192.0.2.1", 443)),
            ],
            connection.method_calls,
        )

    def test_http_error_identifies_endpoint_without_query_values(self):
        client = self.bridge.SafeHTTPClient()
        error = self.bridge.urllib.error.HTTPError(
            "https://umd.instructure.com/api/v1/files/1?verifier=secret",
            406,
            "Not Acceptable",
            {},
            None,
        )
        error.read = mock.Mock(return_value=b"blocked")
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(self.bridge.urllib.request, "build_opener", return_value=opener):
            with self.assertRaisesRegex(
                RuntimeError,
                r"HTTP 406 for https://umd\.instructure\.com/api/v1/files/1: blocked",
            ) as raised:
                client.request("https://umd.instructure.com/api/v1/files/1?verifier=secret")
        self.assertNotIn("secret", str(raised.exception))

    def test_failed_full_sync_preserves_previous_active_course_set(self):
        with self.bridge.db_session() as db:
            db.executemany(
                """
                INSERT INTO courses(id, name, active, json, synced_at)
                VALUES(?, ?, ?, '{}', '2026-01-01T00:00:00+00:00')
                """,
                [("old-active", "Old active", 1), ("old-inactive", "Old inactive", 0)],
            )
            db.commit()
            engine = self.bridge.SyncEngine(db)
            incoming = {
                "id": "new-course",
                "name": "New course",
                "course_code": "NEW100",
                "term": {"name": "Fall 2026"},
            }
            with mock.patch.object(engine.canvas, "paginated", return_value=[incoming]):
                with mock.patch.object(engine, "_sync_course", side_effect=RuntimeError("failed")):
                    with self.assertRaisesRegex(RuntimeError, "failed"):
                        engine.run()
            states = dict(db.execute("SELECT id, active FROM courses"))
        self.assertEqual(1, states["old-active"])
        self.assertEqual(0, states["old-inactive"])
        self.assertEqual(0, states["new-course"])

    def test_attachment_ids_are_found_without_persisting_signed_urls(self):
        description = (
            '<a href="https://umd.instructure.com/courses/1401732/files/87911279'
            '?verifier=secret-value&amp;wrap=1" '
            'data-api-endpoint="https://umd.instructure.com/api/v1/courses/'
            '1401732/files/87911279">HW1_341H.pdf</a>'
        )
        self.assertEqual(
            {"87911279"},
            self.bridge.canvas_file_ids_from_html(description),
        )
        sanitized = self.bridge.sanitize_metadata(
            {
                "description": description,
                "submission": {
                    "preview_url": "https://example.invalid/?verifier=secret-value",
                    "workflow_state": "graded",
                },
            }
        )
        rendered = json.dumps(sanitized)
        self.assertNotIn("secret-value", rendered)
        self.assertNotIn("description", sanitized)
        self.assertEqual("graded", sanitized["submission"]["workflow_state"])

    def test_targeted_sync_arguments_and_missing_files(self):
        args = self.bridge.build_parser().parse_args(
            ["sync", "--course-id", "1401732", "--course-id", "1401780"]
        )
        self.assertEqual(["1401732", "1401780"], args.course_id)
        self.assertTrue(
            self.bridge.unavailable_canvas_file(
                RuntimeError("Remote service returned HTTP 404: missing")
            )
        )
        self.assertFalse(
            self.bridge.unavailable_canvas_file(
                RuntimeError("Remote service returned HTTP 500: retry")
            )
        )


if __name__ == "__main__":
    unittest.main()
