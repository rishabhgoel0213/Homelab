#!/usr/bin/env python3
"""Unit tests for the Zen Space Router Jev service."""

from __future__ import annotations

import importlib.util
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import httpx

SCRIPT_PATH = Path(
    os.environ.get(
        "ZEN_SPACE_ROUTER_SCRIPT",
        str(Path(__file__).resolve().parent.parent / "server.py"),
    )
)
SPEC = importlib.util.spec_from_file_location("zen_space_router_server", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


SPACES = [
    {"uuid": "{default}", "name": "Default"},
    {"uuid": "{school}", "name": "School"},
    {"uuid": "{server}", "name": "Server"},
    {"uuid": "{finances}", "name": "Finances"},
    {"uuid": "{apps}", "name": "Apps"},
]


class FakeHTTPClient:
    def __init__(self, responses: list[dict[str, Any]] | Exception) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any]) -> Any:
        self.calls.append({"url": url, "json": json})
        if isinstance(self.responses, Exception):
            raise self.responses
        body = self.responses.pop(0)

        class _Resp:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict[str, Any]:
                return body

        return _Resp()


def make_jev_answer(
    choice: str,
    confidence: float,
    should_move: float,
) -> dict[str, Any]:
    return {
        "model": "jev-1.14.0",
        "answers": {
            "target_space": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: confidence},
            },
            "should_move": {
                "type": "noul",
                "noul": should_move,
            },
        },
    }


class TestZenSpaceRouter(unittest.TestCase):
    def test_non_routable_urls_skip_jev(self) -> None:
        client = FakeHTTPClient([])
        router = MOD.JevRouter("test-key", http_client=client)

        for url in [
            "about:newtab",
            "about:blank",
            "moz-extension://abc/popup.html",
            "https://accounts.google.com/o/oauth2/v2/auth?client_id=1",
            "https://shib.idm.umd.edu/shibboleth-idp/profile/SAML2/Redirect/SSO",
            "https://api-123.duosecurity.com/frame/v4/auth/prompt",
        ]:
            res = router.route(
                {
                    "url": url,
                    "title": "Sign in",
                    "currentSpaceId": "{default}",
                    "spaces": SPACES,
                }
            )
            self.assertEqual(res["action"], "stay", url)
            self.assertEqual(res["source"], "rules", url)
        self.assertEqual(len(client.calls), 0)

    def test_routes_single_purpose_host_and_caches_by_host(self) -> None:
        client = FakeHTTPClient([make_jev_answer("School", 0.96, 0.98)])
        router = MOD.JevRouter("test-key", http_client=client)

        first = router.route(
            {
                "url": "https://umd.instructure.com/courses/1/assignments/2",
                "title": "CMSC216 Project 4",
                "currentSpaceId": "{default}",
                "currentSpaceName": "Default",
                "spaces": SPACES,
            }
        )
        self.assertEqual(first["action"], "move")
        self.assertEqual(first["source"], "jev")
        self.assertEqual(first["targetSpaceId"], "{school}")
        self.assertEqual(first["targetSpaceName"], "School")
        self.assertEqual(len(client.calls), 1)

        # Second URL on the same single-purpose host should hit cache.
        second = router.route(
            {
                "url": "https://umd.instructure.com/courses/2/grades",
                "title": "Grades",
                "currentSpaceId": "{default}",
                "currentSpaceName": "Default",
                "spaces": SPACES,
            }
        )
        self.assertEqual(second["action"], "move")
        self.assertEqual(second["source"], "cache")
        self.assertEqual(second["targetSpaceId"], "{school}")
        self.assertEqual(len(client.calls), 1)

    def test_multi_topic_host_does_not_collide_across_pages(self) -> None:
        client = FakeHTTPClient(
            [
                make_jev_answer("School", 0.91, 0.90),
                make_jev_answer("Default", 0.93, 0.92),
            ]
        )
        router = MOD.JevRouter("test-key", http_client=client)

        lecture = router.route(
            {
                "url": "https://www.youtube.com/watch?v=abc123",
                "title": "MIT 6.824 Distributed Systems Lecture 1",
                "currentSpaceId": "{default}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(lecture["action"], "move")
        self.assertEqual(lecture["targetSpaceId"], "{school}")

        gaming = router.route(
            {
                "url": "https://www.youtube.com/watch?v=xyz999",
                "title": "Top 10 Cooking Fails",
                "currentSpaceId": "{school}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(gaming["action"], "move")
        self.assertEqual(gaming["targetSpaceId"], "{default}")
        self.assertEqual(len(client.calls), 2)

    def test_low_confidence_or_low_should_move_stays(self) -> None:
        client = FakeHTTPClient(
            [
                make_jev_answer("Finances", 0.45, 0.95),
                make_jev_answer("Finances", 0.95, 0.30),
            ]
        )
        router = MOD.JevRouter("test-key", http_client=client)

        low_conf = router.route(
            {
                "url": "https://example-one.test/page",
                "title": "Ambiguous",
                "currentSpaceId": "{default}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(low_conf["action"], "stay")
        self.assertEqual(low_conf["reason"], "low_confidence")

        low_move = router.route(
            {
                "url": "https://example-two.test/page",
                "title": "Popup",
                "currentSpaceId": "{default}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(low_move["action"], "stay")
        self.assertEqual(low_move["reason"], "low_should_move")

    def test_already_in_target_space_stays(self) -> None:
        client = FakeHTTPClient([make_jev_answer("Server", 0.99, 0.99)])
        router = MOD.JevRouter("test-key", http_client=client)

        res = router.route(
            {
                "url": "https://t3code.internal.therealrishabh.com/",
                "title": "T3 Code",
                "currentSpaceId": "{server}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(res["action"], "stay")
        self.assertEqual(res["reason"], "already_in_space")

    def test_upstream_failure_fails_open(self) -> None:
        client = FakeHTTPClient(httpx.ConnectTimeout("timeout"))
        router = MOD.JevRouter("test-key", http_client=client)

        res = router.route(
            {
                "url": "https://chase.com/dashboard",
                "title": "Chase",
                "currentSpaceId": "{default}",
                "spaces": SPACES,
            }
        )
        self.assertEqual(res["action"], "stay")
        self.assertEqual(res["reason"], "upstream_error")

    def test_http_endpoints(self) -> None:
        client = FakeHTTPClient([make_jev_answer("Finances", 0.97, 0.96)])
        router = MOD.JevRouter("test-key", http_client=client)
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), MOD.make_handler(router))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with httpx.Client(verify=False, trust_env=False, timeout=2.0) as http:
                health = http.get(f"http://127.0.0.1:{port}/health")
                self.assertEqual(health.status_code, 200)
                self.assertTrue(health.json()["ok"])

                route = http.post(
                    f"http://127.0.0.1:{port}/route",
                    content=json.dumps(
                        {
                            "url": "https://investor.vanguard.com/",
                            "title": "Vanguard",
                            "currentSpaceId": "{default}",
                            "spaces": SPACES,
                        }
                    ),
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(route.status_code, 200)
                body = route.json()
                self.assertEqual(body["action"], "move")
                self.assertEqual(body["targetSpaceId"], "{finances}")

                cleared = http.delete(f"http://127.0.0.1:{port}/cache")
                self.assertEqual(cleared.status_code, 200)
                self.assertEqual(cleared.json()["cleared"], 1)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()
