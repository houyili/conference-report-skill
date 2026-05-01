import os
import unittest
from unittest import mock

from conference_report.auth import get_openai_api_key


class AuthTests(unittest.TestCase):
    def test_env_key_takes_precedence(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "env-key"}):
            self.assertEqual(get_openai_api_key(), "env-key")


if __name__ == "__main__":
    unittest.main()
