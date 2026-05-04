from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from conference_report import cli
from conference_report.config import DEFAULT_CONFIG, load_config, write_default_config
from conference_report.utils import write_json


class ConfigProfileTests(unittest.TestCase):
    def test_fast_profile_disables_optional_audio_preservation(self):
        cfg = load_config(None, profile="fast")

        self.assertFalse(cfg["asr"]["save_audio"])
        self.assertFalse(cfg["asr"]["audio_required"])
        self.assertTrue(DEFAULT_CONFIG["asr"]["save_audio"])

    def test_init_config_writes_fast_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"

            result = cli.main(["init-config", str(path), "--profile", "fast"])

            self.assertEqual(result, 0)
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            self.assertFalse(data["asr"]["save_audio"])
            self.assertFalse(data["asr"]["audio_required"])

    def test_build_without_config_writes_run_local_fast_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            seen: dict[str, object] = {}

            def fake_run_asr(source: str, target: Path, cfg: dict[str, object], **kwargs):
                seen["source"] = source
                seen["out"] = target
                seen["save_audio"] = cfg["asr"]["save_audio"]
                seen["audio_required"] = cfg["asr"]["audio_required"]

            def fake_generate_reports(target: Path, cfg: dict[str, object], *, writer: str | None = None, **kwargs):
                reports = target / "reports"
                reports.mkdir(parents=True, exist_ok=True)
                report = reports / "talk.md"
                report.write_text("# Evidence\n", encoding="utf-8")
                write_json(
                    target / "reports_manifest.json",
                    {
                        "writer_mode": "evidence",
                        "reports": [str(report.resolve())],
                    },
                )
                return [report]

            with (
                mock.patch("conference_report.cli.ingest"),
                mock.patch("conference_report.cli.run_asr", side_effect=fake_run_asr),
                mock.patch("conference_report.cli.extract_slides"),
                mock.patch("conference_report.cli.dedupe_slides", return_value={"semantic_review_task_count": 0}),
                mock.patch("conference_report.cli.segment"),
                mock.patch("conference_report.cli.generate_reports", side_effect=fake_generate_reports),
                mock.patch("conference_report.cli.validate_run", return_value={"ok": True}),
            ):
                result = cli.main(["build", "URL", "--out", str(out), "--profile", "fast", "--writer", "evidence"])

            self.assertEqual(result, 0)
            self.assertEqual(seen["source"], "URL")
            self.assertEqual(seen["out"], out.resolve())
            self.assertFalse(seen["save_audio"])
            self.assertFalse(seen["audio_required"])
            run_config = out / "run-config.yaml"
            self.assertTrue(run_config.exists())
            data = yaml.safe_load(run_config.read_text(encoding="utf-8"))
            self.assertFalse(data["asr"]["save_audio"])

    def test_write_default_config_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "config.yaml"

            write_default_config(path, profile="fast")

            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
