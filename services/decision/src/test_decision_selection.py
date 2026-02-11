import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure we can import worker from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock dependencies GLOBALLY before any other import
# This is necessary because the worker imports these at module level
sys.modules["redis"] = MagicMock()
sys.modules["psycopg2"] = MagicMock()
sys.modules["psycopg2.extras"] = MagicMock()
sys.modules["requests"] = MagicMock()

import worker
from constants import KB_BASE_CONFIDENCE, AI_BASE_CONFIDENCE

class TestDecisionSelection(unittest.TestCase):
    
    @patch('worker.match_kb')
    @patch('worker.previous_decision')
    @patch('worker.log') # suppress logs
    def test_history_wins_if_eligible(self, mock_log, mock_prev, mock_kb):
        # Setup
        evt = {"fingerprint": "fp1", "alertname": "test"}
        
        # History returns valid score > 85
        mock_prev.return_value = ({"summary": "hist"}, {"score_final": 90.0, "gating_reason": None})
        # KB matches
        mock_kb.return_value = {"kb_id": 123, "summary": "kb", "checks": [], "fixes": []}
        
        # Act
        decision = worker.make_decision(evt)
        
        # Assert
        self.assertEqual(decision["path"], "history")
        self.assertEqual(decision["confidence"], 90.0)
    
    @patch('worker.match_kb')
    @patch('worker.previous_decision')
    @patch('worker.log')
    def test_kb_wins_if_history_low(self, mock_log, mock_prev, mock_kb):
        # Setup
        # History returns None (ineligible)
        mock_prev.return_value = (None, {"score_final": 50.0, "gating_reason": "score_low"})
        # KB matches
        mock_kb.return_value = {"kb_id": 123, "summary": "kb", "checks": [], "fixes": []}
        
        # Act
        decision = worker.make_decision(evt={"fingerprint": "fp1"})
        
        # Assert
        self.assertEqual(decision["path"], "kb")
        self.assertEqual(decision["confidence"], 60) # Constant KB_BASE_CONFIDENCE

    @patch('worker.match_kb')
    @patch('worker.previous_decision')
    @patch('worker._call_brain_gateway')
    @patch('worker.log')
    def test_fallback_wins_if_nothing_else(self, mock_log, mock_brain, mock_prev, mock_kb):
        mock_prev.return_value = (None, {})
        mock_kb.return_value = None
        mock_brain.return_value = (None, "timeout", None)
        
        decision = worker.make_decision(evt={"fingerprint": "fp1"})
        
        self.assertEqual(decision["path"], "fallback")
        self.assertEqual(decision["confidence"], 40) # Constant AI_BASE_CONFIDENCE

    @patch('worker.match_kb')
    @patch('worker.previous_decision')
    @patch('worker._call_brain_gateway')
    @patch('worker.log')
    def test_manual_ai_trigger(self, mock_log, mock_brain, mock_prev, mock_kb):
        # Even if history and KB exist
        mock_prev.return_value = ({"summary": "hist"}, {"score_final": 95.0})
        mock_kb.return_value = {"kb_id": 1, "summary": "kb", "checks": [], "fixes": []}
        mock_brain.return_value = (
            {
                "schemaVersion": "1.0",
                "requestId": "00000000-0000-0000-0000-000000000000",
                "provider": "openai",
                "model": "gpt-test",
                "summary": "AI summary",
                "triage": {"severity": "info", "confidence": 0.5, "category": "test"},
                "hypotheses": [],
                "recommendedActions": [],
                "checks": [],
                "fixes": [],
            },
            None,
            10,
        )
        
        evt = {"fingerprint": "fp1", "force_ai": True}
        
        decision = worker.make_decision(evt)
        
        # Should be AI (manual)
        self.assertEqual(decision["path"], "ai") # "ai" if manual per code
        self.assertEqual(decision["confidence"], 40) 
        self.assertIn("triggered_by=manual", decision["reason"])

if __name__ == '__main__':
    unittest.main()
