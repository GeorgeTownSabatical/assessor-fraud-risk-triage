from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from assessor_fraud_risk_triage.io import read_csv
from assessor_fraud_risk_triage.scoring import result_rows, score_records


ROOT = Path(__file__).resolve().parents[1]


class ScoringTests(unittest.TestCase):
    def test_synthetic_chain_scores_high(self) -> None:
        results, chains, _edges, summary = score_records(
            read_csv(ROOT / "examples" / "instruments.csv"),
            read_csv(ROOT / "examples" / "cases.csv"),
            read_csv(ROOT / "examples" / "entities.csv"),
        )
        rows = {row["document_number"]: row for row in result_rows(results)}
        self.assertEqual(summary["status"], "triage_summary_not_fraud_finding")
        self.assertGreaterEqual(float(rows["202400000102"]["score"]), 80)
        self.assertEqual(rows["202400000102"]["band"], "high_review")
        self.assertTrue(any(chain["pattern"] == "rapid_transfer_to_trust_deed" for chain in chains))

    def test_ordinary_is_low_context(self) -> None:
        results, _chains, _edges, _summary = score_records(read_csv(ROOT / "examples" / "instruments.csv"))
        rows = {row["document_number"]: row for row in result_rows(results)}
        self.assertEqual(rows["202400000310"]["band"], "low_context")
        self.assertIn("triage_lead_not_fraud_finding", rows["202400000310"]["status"])

    def test_no_accusatory_status_language(self) -> None:
        results, chains, _edges, summary = score_records(read_csv(ROOT / "examples" / "instruments.csv"))
        payload = str(result_rows(results)) + str(chains) + str(summary)
        self.assertNotIn("fraud_finding", payload.replace("not_fraud_finding", ""))

    def test_party_names_alias_is_used(self) -> None:
        results, _chains, _edges, _summary = score_records(
            [
                {
                    "document_number": "1",
                    "recording_date": "2024-01-01",
                    "document_type": "GRANT DEED",
                    "party_names": "Alias Person | Alias LLC",
                }
            ]
        )
        rows = result_rows(results)
        self.assertEqual(rows[0]["parties"], "Alias Person | Alias LLC")
        self.assertIn("entity_counterparty", rows[0]["factors"])


if __name__ == "__main__":
    unittest.main()
