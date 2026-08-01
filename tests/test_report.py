import json
import tempfile
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parents[1]))
import solana_report


class ReportTests(unittest.TestCase):
    def test_performance_uses_total_window(self):
        result = solana_report.calculate_performance(
            [
                {"numSlots": 100, "numTransactions": 2_000, "samplePeriodSecs": 2},
                {"numSlots": 100, "numTransactions": 3_000, "samplePeriodSecs": 3},
            ]
        )
        self.assertEqual(result["transactions"], 5_000)
        self.assertEqual(result["sampleSeconds"], 5.0)
        self.assertEqual(result["transactionsPerSecond"], 1_000.0)
        self.assertEqual(result["secondsPerSlot"], 0.025)

    def test_validator_metrics_sorts_by_stake(self):
        result = solana_report.validator_metrics(
            {"current": [{"voteAccountPubkey": "small", "activatedStake": 2}, {"voteAccountPubkey": "large", "activatedStake": 8}], "delinquent": []}
        )
        self.assertEqual(result["active"], 2)
        self.assertEqual(result["topValidators"][0]["voteAccount"], "large")
        self.assertEqual(result["topValidators"][0]["sharePercent"], 80.0)

    def test_anomaly_detection_is_conservative(self):
        old = {"solana": {"performance": {"transactionsPerSecond": 100}, "validators": {"delinquent": 2}}, "market": {"tvlUsd": 1000, "solUsd": 100}}
        new = {"solana": {"performance": {"transactionsPerSecond": 60}, "validators": {"delinquent": 8}}, "market": {"tvlUsd": 800, "solUsd": 100}}
        alerts = solana_report.detect_anomalies(new, old)
        self.assertEqual({a["metric"] for a in alerts}, {"TPS", "delinquent validators", "TVL"})

    def test_sample_writes_auditable_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = solana_report.run_once(root, solana_report.DEFAULT_RPC_URL, True)
            self.assertEqual(report["solana"]["health"], "ok")
            self.assertTrue((root / "reports/latest.json").exists())
            self.assertTrue((root / "reports/latest.md").exists())
            self.assertTrue((root / "web/index.html").exists())
            json.loads((root / "web/latest.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
