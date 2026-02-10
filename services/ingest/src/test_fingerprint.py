import unittest
from fingerprint import calculate_fingerprint

class TestFingerprint(unittest.TestCase):
    
    def test_determinism(self):
        alert = {"labels": {"alertname": "Test", "pod": "test-pod-abcd"}}
        fp1, ex1 = calculate_fingerprint(alert)
        fp2, ex2 = calculate_fingerprint(alert)
        self.assertEqual(fp1, fp2)
        self.assertEqual(ex1, ex2)
        
    def test_replicaset_normalization_strict(self):
        # Full k8s pattern: name-hash-hash -> Groups
        a1 = {"labels": {"alertname": "Crash", "pod": "api-7f8c9d5d6b-abcde", "namespace": "prod"}}
        a2 = {"labels": {"alertname": "Crash", "pod": "api-7f8c9d5d6b-fghij", "namespace": "prod"}}
        
        fp1, ex1 = calculate_fingerprint(a1)
        fp2, ex2 = calculate_fingerprint(a2)
        
        self.assertEqual(fp1, fp2)
        self.assertEqual(ex1['inputs']['derived_workload'], "api")
        self.assertEqual(ex1['scope'], "workload")
        
    def test_replicaset_normalization_ignores_short_hash(self):
        # Only one hash -> DOES NOT normalize (could be unique pod name or manual)
        a1 = {"labels": {"alertname": "Crash", "pod": "api-7f8c9d", "namespace": "prod"}}
        a2 = {"labels": {"alertname": "Crash", "pod": "api-123456", "namespace": "prod"}}
        
        fp1, ex1 = calculate_fingerprint(a1)
        fp2, ex2 = calculate_fingerprint(a2)
        
        # Should differ because they didn't match strict RS regex
        self.assertNotEqual(fp1, fp2)
        self.assertEqual(ex1['scope'], "pod")
        self.assertEqual(ex1['inputs']['pod'], "api-7f8c9d")
        
    def test_statefulset_differentiation(self):
        # Different pods from STS should NOT group
        a1 = {"labels": {"alertname": "Crash", "pod": "redis-0", "namespace": "db"}}
        a2 = {"labels": {"alertname": "Crash", "pod": "redis-1", "namespace": "db"}}
        
        fp1, ex1 = calculate_fingerprint(a1)
        fp2, ex2 = calculate_fingerprint(a2)
        
        self.assertNotEqual(fp1, fp2)
        self.assertEqual(ex1['inputs']['pod'], "redis-0")
        self.assertEqual(ex2['inputs']['pod'], "redis-1")
        
    def test_missing_namespace_placeholder(self):
        alert = {"labels": {"alertname": "Foo"}}
        fp, ex = calculate_fingerprint(alert)
        self.assertEqual(ex['namespace'], "__none__")
        
    def test_node_priority(self):
        alert = {"labels": {"alertname": "NodeNotReady", "node": "worker-1", "pod": "ignored-pod"}}
        fp, ex = calculate_fingerprint(alert)
        
        self.assertEqual(ex['scope'], "node")
        self.assertIn("node", ex['inputs'])
        self.assertNotIn("pod", ex['inputs'])
        self.assertNotIn("derived_workload", ex['inputs'])
        
    def test_explicit_controller_priority(self):
        # If deployment label exists, use it over pod name
        alert = {"labels": {"alertname": "ReplicasMismatch", "deployment": "backend", "pod": "backend-xyz-123", "namespace": "prod"}}
        fp, ex = calculate_fingerprint(alert)
        
        self.assertEqual(ex['scope'], "workload")
        self.assertEqual(ex['inputs']['controller'], "backend")
        self.assertNotIn("pod", ex['inputs'])
        
    def test_global_scope(self):
        alert = {"labels": {"alertname": "ClusterDegraded"}}
        fp, ex = calculate_fingerprint(alert)
        
        self.assertEqual(ex['scope'], "global")
        self.assertEqual(ex['inputs'], {"alertname": "ClusterDegraded"})
