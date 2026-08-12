import importlib.util
import os
import sys
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(
    os.environ.get(
        "SINGLEMAIL_SCRIPT",
        Path(__file__).parent.parent / "scripts" / "singlemail.py",
    )
)


def load_singlemail():
    spec = importlib.util.spec_from_file_location("singlemail_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SinglemailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.singlemail = load_singlemail()

    def test_duration_parser(self):
        self.assertEqual(1800, self.singlemail.parse_duration("30m"))
        self.assertEqual(7200, self.singlemail.parse_duration("2h"))
        self.assertEqual(86400, self.singlemail.parse_duration("1d"))
        with self.assertRaises(Exception):
            self.singlemail.parse_duration("4m")
        with self.assertRaises(Exception):
            self.singlemail.parse_duration("8d")

    def test_plain_message_extracts_code_and_links(self):
        message = EmailMessage()
        message["From"] = "Example <no-reply@example.com>"
        message["To"] = "abcd@inbox.example.com"
        message["Subject"] = "Your verification code is 483921"
        message.set_content(
            "Enter 483921 to continue. Or visit https://example.com/verify?t=safe-token."
        )
        parsed = self.singlemail.parse_raw_message(message.as_bytes())
        self.assertEqual(["483921"], parsed["codes"])
        self.assertEqual(["https://example.com/verify?t=safe-token"], parsed["links"])
        self.assertIn("Enter 483921", parsed["text"])

    def test_html_message_is_rendered_inertly(self):
        message = EmailMessage()
        message["From"] = "Example <no-reply@example.com>"
        message["To"] = "abcd@inbox.example.com"
        message["Subject"] = "Confirm A8B21Z"
        message.set_content(
            """
            <html><body>
              <script>stealToken()</script>
              <style>.hidden { display:none }</style>
              <p>Confirmation code <strong>A8B21Z</strong></p>
              <a href="https://example.com/confirm?token=abc">Confirm</a>
              <a href="javascript:alert(1)">Bad</a>
            </body></html>
            """,
            subtype="html",
        )
        parsed = self.singlemail.parse_raw_message(message.as_bytes())
        self.assertNotIn("stealToken", parsed["text"])
        self.assertNotIn("display:none", parsed["text"])
        self.assertIn("A8B21Z", parsed["codes"])
        self.assertEqual(["https://example.com/confirm?token=abc"], parsed["links"])

    def test_link_extraction_deduplicates(self):
        links = self.singlemail.extract_links(
            "Visit https://example.com/a and https://example.com/a.",
            ["https://example.com/a"],
        )
        self.assertEqual(["https://example.com/a"], links)

    def test_present_inbox_adds_dates_without_removing_epoch(self):
        inbox = {
            "id": "one",
            "created_at": 1_700_000_000,
            "expires_at": None,
            "closed_at": None,
        }
        rendered = self.singlemail.present_inbox(inbox)
        self.assertEqual(1_700_000_000, rendered["created_at"])
        self.assertTrue(rendered["created_at_iso"].endswith("+00:00"))
        self.assertIsNone(rendered["expires_at_iso"])

    def test_page_contains_no_worker_token(self):
        page = self.singlemail.render_home().decode()
        self.assertIn("Singlemail", page)
        self.assertNotIn("SINGLEMAIL_API_TOKEN", page)
        self.assertNotIn("Authorization", page)

    def test_worker_requests_identify_the_client(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"ready":true}'

        client = self.singlemail.WorkerClient("https://worker.example", "test-token")
        with patch.object(
            self.singlemail.urllib.request, "urlopen", return_value=Response()
        ) as urlopen:
            client.health()

        request = urlopen.call_args.args[0]
        self.assertEqual("Singlemail/0.1.0", request.get_header("User-agent"))


if __name__ == "__main__":
    unittest.main()
