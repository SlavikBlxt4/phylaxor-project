import unittest
import datetime
from history_score import calculate_score

# Helpers
def _row(path='history', conf=100.0, days_ago=0, summary="Fix it"):
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_ago)
    return {
        "path": path,
        "confidence": conf,
        "created_at": dt,
        "recommendation": {"summary": summary},
        "id": 1
    }

class TestHistoryScore(unittest.TestCase):
    
    def test_insufficient_samples(self):
        # Only 2 rows, min 3
        rows = [_row() for _ in range(2)]
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["gating_reason"], "insufficient_samples")
        
    def test_fallback_ignored(self):
        # 4 rows, but 2 are fallback -> only 2 valid -> insufficient
        rows = [_row(), _row(), _row(path='fallback'), _row(path='fallback')]
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["valid_count"], 2)
        
    def test_freshness_check(self):
        # 3 rows, but one is 31 days old (limit 30) -> 2 valid
        rows = [
            _row(days_ago=1),
            _row(days_ago=2),
            _row(days_ago=31)
        ]
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["valid_count"], 2)

    def test_consensus_failure(self):
        # 3 rows, all valid, but diverse summaries
        rows = [
            _row(summary="Option A"),
            _row(summary="Option B"),
            _row(summary="Option C")
        ]
        # Consensus ratio = 1/3 = 0.33 < 0.6
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["gating_reason"], "low_consensus")
        self.assertAlmostEqual(reason["consensus_ratio"], 0.33, places=2)

    def test_score_threshold_failure(self):
        # 3 rows, consensus OK, but low confidence
        rows = [
            _row(conf=50),
            _row(conf=50),
            _row(conf=50)
        ]
        # Score approx 50 < 85
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["gating_reason"], "score_below_threshold")
        self.assertAlmostEqual(reason["score_final"], 50.0, places=1)
        
    def test_variance_penalty(self):
        # High avg but high variance
        # 100, 100, 40 -> avg ~80, stdev high
        rows = [
            _row(conf=100),
            _row(conf=100),
            _row(conf=40)
        ]
        eligible, rec, reason = calculate_score(rows)
        # Avg ~80, Stdev ~34. Penalty ~8.5. Final ~71.5
        # Should fail (threshold 85)
        self.assertFalse(eligible)
        self.assertTrue(reason["score_penalty"] > 5.0)

    def test_success_case(self):
        rows = [
            _row(conf=100, days_ago=1),
            _row(conf=95, days_ago=2),
            _row(conf=100, days_ago=3)
        ]
        eligible, rec, reason = calculate_score(rows)
        self.assertTrue(eligible)
        self.assertEqual(rec["summary"], "Fix it")
        self.assertTrue(reason["score_final"] > 85)

    def test_weighted_selection(self):
        # ... existing verification ...
        rows = [
            _row(days_ago=20, summary="Old Way"),
            _row(days_ago=20, summary="Old Way"),
            _row(days_ago=20, summary="Old Way"),
            _row(days_ago=1, summary="New Way"),
            _row(days_ago=1, summary="New Way"),
        ]
        eligible, rec, reason = calculate_score(rows)
        self.assertTrue(eligible, f"Should be eligible. Reason: {reason}")
        self.assertEqual(rec["summary"], "New Way")
        self.assertEqual(reason["chosen_recommendation_key"], "New Way")

    def test_all_too_old_gating(self):
        # 3 rows, all older than 30 days
        rows = [
            _row(days_ago=31),
            _row(days_ago=40),
            _row(days_ago=50)
        ]
        eligible, rec, reason = calculate_score(rows)
        self.assertFalse(eligible)
        self.assertEqual(reason["gating_reason"], "all_history_too_old")
        self.assertFalse(reason["freshness_ok"])
        self.assertEqual(reason["dropped_due_to_age"], 3)
        self.assertEqual(reason["valid_count"], 0)

    def test_id_based_consensus(self):
        # Summaries differ, but kb_id is consistent
        # Rows: path=kb, kb_id=10
        # Should group by kb:10 despite summary difference
        r1 = _row(days_ago=1, summary="A")
        r1.update({"path": "kb", "kb_id": 10})
        
        r2 = _row(days_ago=1, summary="B")
        r2.update({"path": "kb", "kb_id": 10})
        
        r3 = _row(days_ago=1, summary="C")
        r3.update({"path": "kb", "kb_id": 10})
        
        # All have kb_id 10 -> key "kb:10" -> group size 3 -> consensus ratio 1.0
        eligible, rec, reason = calculate_score([r1, r2, r3])
        
        self.assertTrue(eligible, f"Should group by kb_id. Reason: {reason}")
        self.assertIn("kb:10", reason["chosen_recommendation_key"])
        self.assertEqual(reason["consensus_ratio"], 1.0)

    def test_debug_reason_includes_details(self):
        rows = [_row() for _ in range(2)]
        eligible, rec, reason = calculate_score(rows, debug=True)
        self.assertIn("rows_used", reason)
        self.assertIn("config_effective", reason)
        self.assertIsInstance(reason["rows_used"], list)
        self.assertIsInstance(reason["config_effective"], dict)


if __name__ == '__main__':
    unittest.main()
