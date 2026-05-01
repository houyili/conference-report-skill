import tempfile
import unittest
from pathlib import Path

from conference_report.asr import vtt_to_rows
from conference_report.utils import format_time, parse_time_seconds


class TimeTests(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(format_time(parse_time_seconds("01:02:03.456")), "01:02:03.456")


class VttTests(unittest.TestCase):
    def test_vtt_to_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.vtt"
            path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello <b>world</b>\n\n", encoding="utf-8")
            rows = vtt_to_rows(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["time"], "00:00:01.000")
            self.assertEqual(rows[0]["text"], "Hello world")


if __name__ == "__main__":
    unittest.main()
