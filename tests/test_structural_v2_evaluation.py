import json
from collections import Counter
from pathlib import Path
import unittest


class StructuralV2EvaluationTests(unittest.TestCase):
    def test_independent_corpus_has_frozen_36_case_split(self):
        root = Path(__file__).resolve().parents[1] / "evaluation" / "structural_v2"
        cases = json.loads((root / "corpus_manifest.json").read_text())["cases"]
        self.assertEqual(len(cases), 36)
        self.assertEqual(Counter(item["domain"] for item in cases), {"spatial": 12, "operator": 12, "xc": 12})
        self.assertEqual(Counter(item["split"] for item in cases), {"development": 24, "evaluation": 12})
        self.assertTrue(all("expected" in item and "rationale" in item for item in cases))
