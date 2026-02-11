import unittest
from unittest.mock import MagicMock, patch
import sys
import os
import types
import uuid

# Ensure we can import worker from current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock external dependencies before import
sys.modules["redis"] = MagicMock()
sys.modules["psycopg2"] = MagicMock()
sys.modules["psycopg2.extras"] = MagicMock()

requests_mock = types.SimpleNamespace()

class Timeout(Exception):
    pass

class RequestException(Exception):
    pass

requests_mock.exceptions = types.SimpleNamespace(
    Timeout=Timeout,
    RequestException=RequestException,
)
requests_mock.post = MagicMock()
sys.modules["requests"] = requests_mock

import worker


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _evt():
    return {
        "fingerprint": "fp1",
        "alertname": "TestAlert",
        "status": "firing",
        "startsAt": "2024-01-01T00:00:00Z",
        "labels": {"namespace": "default", "pod": "mypod", "severity": "warning"},
        "annotations": {"summary": "Test alert"},
        "context": {
            "alert": {
                "namespace": "default",
                "pod": "mypod",
                "events": [],
                "logs": None,
            },
            "cluster": {
                "platform": "k8s",
                "version": "1.27.0",
                "nodes": 1,
                "nodeSummary": {"ready": 1, "notReady": 0},
                "defaultStorageClass": None,
            },
        },
    }


class TestBrainGatewayIntegration(unittest.TestCase):
    def test_brain_gateway_success_smoke(self):
        captured = {}

        def fake_post(url, json, timeout):
            captured["url"] = url
            captured["payload"] = json
            captured["timeout"] = timeout
            ai_resp = {
                "schemaVersion": "1.0",
                "requestId": json["meta"]["requestId"],
                "provider": "openai",
                "model": "gpt-test",
                "summary": "AI summary",
                "triage": {"severity": "info", "confidence": 0.5, "category": "test"},
                "hypotheses": [],
                "recommendedActions": [],
                "checks": [],
                "fixes": [],
                "usage": {"inputTokens": 10, "outputTokens": 5, "estimatedCostUsd": 0.0001, "latencyMs": 12},
            }
            return _Resp(200, ai_resp)

        requests_mock.post.side_effect = fake_post

        with patch("worker.previous_decision") as mock_prev, \
             patch("worker.match_kb") as mock_kb, \
             patch("worker.log") as mock_log:
            mock_prev.return_value = (None, {"gating_reason": "no_history"})
            mock_kb.return_value = None

            decision = worker.make_decision(_evt())

        self.assertTrue(captured["url"].endswith("/v1/brain/complete"))
        payload = captured["payload"]
        self.assertIn("meta", payload)
        self.assertIn("alert", payload)
        self.assertIn("context", payload)
        self.assertIn("constraints", payload)
        self.assertIn("outputFormat", payload)
        self.assertEqual(payload["alert"]["fingerprint"], "fp1")
        self.assertEqual(payload["constraints"]["readOnly"], True)
        self.assertIn("alertContext", payload["context"])
        self.assertIn("cluster", payload["context"])
        uuid.UUID(payload["meta"]["requestId"])

        self.assertEqual(decision["path"], "ai")
        self.assertEqual(decision["rec"]["summary"], "AI summary")

        # Verify request_id + fingerprint present in logs
        brain_logs = [c for c in mock_log.call_args_list if c.args and c.args[0] == "brain_request"]
        self.assertTrue(brain_logs)
        kwargs = brain_logs[0].kwargs
        self.assertEqual(kwargs.get("fingerprint"), "fp1")
        self.assertIsNotNone(kwargs.get("request_id"))

    def test_brain_gateway_502_fallback(self):
        def fake_post(url, json, timeout):
            return _Resp(502, {"detail": "bad gateway"})

        requests_mock.post.side_effect = fake_post

        with patch.object(worker, "BRAIN_GATEWAY_MAX_RETRIES", 0), \
             patch.object(worker.time, "sleep") as _sleep, \
             patch("worker.previous_decision") as mock_prev, \
             patch("worker.match_kb") as mock_kb, \
             patch("worker.log"):
            mock_prev.return_value = (None, {"gating_reason": "no_history"})
            mock_kb.return_value = None
            decision = worker.make_decision(_evt())

        self.assertEqual(decision["path"], "fallback")
        self.assertIn("AI backend unavailable", decision["rec"]["missingInfo"])

    def test_brain_gateway_timeout_fallback(self):
        def fake_post(url, json, timeout):
            raise worker.requests.exceptions.Timeout()

        requests_mock.post.side_effect = fake_post

        with patch.object(worker, "BRAIN_GATEWAY_MAX_RETRIES", 0), \
             patch.object(worker.time, "sleep") as _sleep, \
             patch("worker.previous_decision") as mock_prev, \
             patch("worker.match_kb") as mock_kb, \
             patch("worker.log"):
            mock_prev.return_value = (None, {"gating_reason": "no_history"})
            mock_kb.return_value = None
            decision = worker.make_decision(_evt())

        self.assertEqual(decision["path"], "fallback")
        self.assertIn("AI backend unavailable", decision["rec"]["missingInfo"])


if __name__ == "__main__":
    unittest.main()
