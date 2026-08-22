#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import struct
import unittest


SCRIPT = Path(os.environ["REMOTE_PHONE_SCRIPT"])
SPEC = importlib.util.spec_from_file_location("remote_phone_mic", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
REMOTE_PHONE_MIC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REMOTE_PHONE_MIC)


class RemotePhoneMicTests(unittest.TestCase):
    def test_tailnet_ranges(self) -> None:
        self.assertTrue(REMOTE_PHONE_MIC.is_tailnet_address("100.64.0.1"))
        self.assertTrue(
            REMOTE_PHONE_MIC.is_tailnet_address("fd7a:115c:a1e0::1234")
        )
        self.assertFalse(REMOTE_PHONE_MIC.is_tailnet_address("192.168.1.2"))
        self.assertFalse(REMOTE_PHONE_MIC.is_tailnet_address("127.0.0.1"))

    def test_duration_is_explicitly_bounded(self) -> None:
        self.assertEqual(REMOTE_PHONE_MIC.bounded_duration("5"), 5.0)
        for value in ("0", "-1", "60.1", "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    REMOTE_PHONE_MIC.bounded_duration(value)

    def test_close_codes_have_safe_operator_errors(self) -> None:
        error = REMOTE_PHONE_MIC.close_frame_error(struct.pack("!H", 4011))
        self.assertIn("disabled", str(error))
        self.assertNotIn("token", str(error).lower())

    def test_capability_summary(self) -> None:
        self.assertEqual(
            REMOTE_PHONE_MIC.microphone_state(
                {"capabilities": {"microphone": {"enabled": True}}}
            ),
            "enabled",
        )
        self.assertEqual(
            REMOTE_PHONE_MIC.microphone_state({"enabled": {"microphone": False}}),
            "disabled",
        )

    def test_blank_audio_marker_is_normalized(self) -> None:
        self.assertEqual(
            REMOTE_PHONE_MIC.normalize_transcript("[BLANK_AUDIO]\n"),
            "",
        )
        self.assertEqual(
            REMOTE_PHONE_MIC.normalize_transcript("[BLANK_AUDIO]\nHello."),
            "Hello.",
        )


if __name__ == "__main__":
    unittest.main()
