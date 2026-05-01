import tempfile
import sys
import unittest
from pathlib import Path
from unittest import mock

from conference_report.asr import vtt_to_rows
from conference_report.config import DEFAULT_CONFIG
from conference_report.report import low_information_reason
from conference_report.segment import aligned_talks, load_manual_segments
from conference_report.utils import format_time, parse_time_seconds, require_tool, write_json


class TimeTests(unittest.TestCase):
    def test_roundtrip(self):
        self.assertEqual(format_time(parse_time_seconds("01:02:03.456")), "01:02:03.456")

    def test_parse_numeric_and_mmss(self):
        self.assertEqual(parse_time_seconds(12.5), 12.5)
        self.assertEqual(parse_time_seconds("12.5"), 12.5)
        self.assertEqual(parse_time_seconds("02:03.500"), 123.5)


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

    def test_manual_segments_are_explicit_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            asr_dir = root / "asr"
            asr_dir.mkdir()
            (asr_dir / "timeline.txt").write_text(
                "[00:00:00.500] Short talk one.\n[00:00:18.000] Short talk two.\n",
                encoding="utf-8",
            )
            write_json(root / "slide_intervals.json", [])
            manual = root / "manual.yaml"
            manual.write_text(
                "talks:\n"
                "  - title: Short One\n"
                "    type: oral\n"
                "    schedule_start: 0.0\n"
                "    schedule_end: 12.0\n"
                "  - title: Break\n"
                "    type: break\n"
                "    schedule_start: 12.0\n"
                "    schedule_end: 17.0\n"
                "  - title: Short Two\n"
                "    type: oral\n"
                "    schedule_start: 17.0\n"
                "    schedule_end: 30.0\n",
                encoding="utf-8",
            )
            talks = aligned_talks(root, DEFAULT_CONFIG, manual_segments=manual)
            self.assertEqual(talks[0]["aligned_start"], "00:00:00.000")
            self.assertEqual(talks[0]["aligned_end"], "00:00:12.000")
            self.assertTrue(talks[0]["reportable"])
            self.assertFalse(talks[1]["reportable"])
            self.assertTrue(talks[2]["reportable"])


class ReportEvidenceTests(unittest.TestCase):
    def test_break_slides_are_low_information_for_talk_reports(self):
        reason = low_information_reason(
            "Retrieval-Augmented Evaluation",
            "Coffee Break No report should be generated for this interval",
            "Welcome to the first talk.",
        )
        self.assertEqual(reason, "break/poster/intermission slide")


if __name__ == "__main__":
    unittest.main()
