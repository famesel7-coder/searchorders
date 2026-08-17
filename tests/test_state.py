from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from searchorders.models import Lead
from searchorders.state import SeenLeadStore, lead_key


class SeenLeadStoreTests(unittest.TestCase):
    def test_returns_lead_only_once(self) -> None:
        lead = Lead(source="workspace", external_id="18857", title="Редизайн сайта")
        with tempfile.TemporaryDirectory() as directory:
            store = SeenLeadStore(Path(directory) / "state.db")
            self.assertEqual(store.only_new([lead]), [lead])
            store.mark_seen([lead])
            self.assertEqual(store.only_new([lead]), [])

    def test_source_is_part_of_key(self) -> None:
        first = Lead(source="workspace", external_id="42", title="Проект")
        second = Lead(source="another-source", external_id="42", title="Проект")
        self.assertNotEqual(lead_key(first), lead_key(second))


if __name__ == "__main__":
    unittest.main()

