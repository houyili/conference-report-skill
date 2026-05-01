import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

from conference_report.asr import vtt_to_rows
from conference_report.segment import load_manual_segments
from conference_report.utils import format_time, parse_time_seconds, require_tool


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


class ToolLookupTests(unittest.TestCase):
    def test_require_tool_finds_current_python_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / ("Scripts" if sys.platform.startswith("win") else "bin")
            bin_dir.mkdir()
            suffix = ".exe" if sys.platform.startswith("win") else ""
            python = bin_dir / f"python{suffix}"
            python.write_text("", encoding="utf-8")
            tool = bin_dir / f"yt-dlp{suffix}"
            tool.write_text("#!/bin/sh\n", encoding="utf-8")
            tool.chmod(0o755)
            with (
                mock.patch("conference_report.utils.shutil.which", return_value=None),
                mock.patch("conference_report.utils.sys.executable", str(python)),
                mock.patch("conference_report.utils.sys.prefix", tmp),
            ):
                self.assertEqual(require_tool("yt-dlp"), str(tool.resolve()))


class ManualSegmentTests(unittest.TestCase):
    def test_manual_segments_accept_top_level_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "segments.yaml"
            path.write_text("- title: Talk\n  type: oral\n", encoding="utf-8")
            self.assertEqual(load_manual_segments(path)[0]["title"], "Talk")


if __name__ == "__main__":
    unittest.main()
