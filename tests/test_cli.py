from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from searchorders.cli import main


class CLITests(unittest.TestCase):
    def test_evaluate_fixture_writes_ranked_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "leads.json"
            code = main(
                [
                    "evaluate",
                    "tests/fixtures/sample_leads.json",
                    "--profile",
                    "data/search-profile.yaml",
                    "--cases",
                    "data/cases.yaml",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["total"], 4)
            self.assertGreaterEqual(payload["summary"]["hot"], 1)
            self.assertGreaterEqual(payload["summary"]["rejected"], 1)


if __name__ == "__main__":
    unittest.main()

