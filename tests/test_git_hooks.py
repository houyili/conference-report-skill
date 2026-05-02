import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "install_git_hooks.py"


def load_script_module():
    spec = importlib.util.spec_from_file_location("install_git_hooks", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GitHookTests(unittest.TestCase):
    def test_installs_pre_push_hook_that_runs_repo_check_script(self):
        hooks = load_script_module()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".git" / "hooks").mkdir(parents=True)
            (repo / "scripts").mkdir()
            (repo / "scripts" / "check_before_push.py").write_text("print('ok')\n", encoding="utf-8")

            hook_path = hooks.install_pre_push_hook(repo, Path(sys.executable))

            self.assertEqual(hook_path, repo / ".git" / "hooks" / "pre-push")
            content = hook_path.read_text(encoding="utf-8")
            self.assertIn(str(repo / "scripts" / "check_before_push.py"), content)
            self.assertIn(str(Path(sys.executable)), content)
            self.assertTrue(os.access(hook_path, os.X_OK))


if __name__ == "__main__":
    unittest.main()
