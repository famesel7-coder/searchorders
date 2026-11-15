from __future__ import annotations
import json
import tempfile
import threading
import unittest
from pathlib import Path
from realtime_service.source_store import canonical_url, list_sources, add_source, remove_source

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.registry = root / "data.json"
        self.state = root / "runtime"
        self.registry.write_text(json.dumps({"source_registry": [
            {"tier":"telegram_primary","url":"https://t.me/s/designs_squad"},
            {"tier":"telegram_primary","url":"https://t.me/s/original_design"},
            {"tier":"other","url":"https://t.me/s/irrelevant_misc"}
        ]}),encoding="utf-8")
        self.state.mkdir()
        (self.state/"extra_sources.json").write_text(json.dumps([
            "https://t.me/s/vakansii_smm",
            "https://t.me/s/vakansii_reelsmaker",
            "https://t.me/s/vakansii_copywriters",
            "https://t.me/s/Designs_job"
        ]),encoding="utf-8")

    def test_remove_three_keep_design_sources(self):
        before = list_sources(self.registry,self.state)
        self.assertEqual(len(before),6)
        for name in ["vakansii_smm","vakansii_reelsmaker","vakansii_copywriters"]:
            result=remove_source("https://t.me/s/"+name,self.registry,self.state)
            self.assertTrue(result["removed"])
        after=list_sources(self.registry,self.state)
        self.assertEqual(len(after),3)
        self.assertIn("https://t.me/s/designs_squad",after)
        self.assertIn("https://t.me/s/designs_job",after)
        self.assertIn("https://t.me/s/original_design",after)
        self.assertTrue((self.state/"excluded_sources.json").exists())

    def test_idempotence_and_readding(self):
        source="https://t.me/s/vakansii_smm"
        self.assertTrue(remove_source(source,self.registry,self.state)["removed"])
        self.assertFalse(remove_source(source,self.registry,self.state)["removed"])
        self.assertTrue(add_source(source,self.registry,self.state)["added"])
        self.assertFalse(add_source(source,self.registry,self.state)["added"])
        self.assertIn(source,list_sources(self.registry,self.state))

    def test_can_hide_base_registry_source(self):
        self.assertTrue(remove_source("https://t.me/s/original_design",self.registry,self.state)["removed"])
        self.assertNotIn("https://t.me/s/original_design",list_sources(self.registry,self.state))
        self.assertTrue(add_source("https://t.me/s/original_design",self.registry,self.state)["added"])

    def test_malformed_rejected_without_mutation(self):
        before=list_sources(self.registry,self.state)
        for url in ["https://evil.com/test","https://t.me/s/bot?x=1","https://t.me/s/a","http://localhost/foo"]:
            with self.assertRaises(ValueError):
                remove_source(url,self.registry,self.state)
        self.assertEqual(before,list_sources(self.registry,self.state))
        self.assertFalse((self.state/"excluded_sources.json").exists())

    def test_case_insensitive_and_concurrency(self):
        result=[]
        def action():
            result.append(remove_source("https://t.me/s/VAKANSII_SMM",self.registry,self.state))
        threads=[threading.Thread(target=action) for _ in range(8)]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(sum(x["removed"] for x in result),1)
        self.assertEqual(len(list_sources(self.registry,self.state)),5)

    def test_malformed_state_file_fails_closed(self):
        p=self.state/"excluded_sources.json"
        p.write_text("{ not valid JSON",encoding="utf-8")
        with self.assertRaises(ValueError):
            remove_source("https://t.me/s/vakansii_smm",self.registry,self.state)
        self.assertEqual(p.read_text(encoding="utf-8"),"{ not valid JSON")

if __name__=="__main__":unittest.main()
