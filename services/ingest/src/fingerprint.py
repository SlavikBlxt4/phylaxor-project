import hashlib
import json
import re

# Denylist: Fields that must NEVER be used
DENYLIST = {
    "instance", "job", "prometheus", "pod_uid", "uid", 
    "image_id", "container_id", "resourceVersion", "status",
    "startsAt", "endsAt", "created_at", "fingerprint"
}

# Strict Regex for standard K8s ReplicaSet/Deployment pod names
# Matches: name + "-" + RS hash (9-10 hex) + "-" + pod hash (5 alphanumeric)
# Example: api-7f8c9d5d6b-xfw2z
# Capture group 1 is the RS hash, group 2 is the random suffix
STRICT_RS_POD_RE = re.compile(r"(-[a-f0-9]{9,10})(-[a-z0-9]{5})$")

def _normalize_pod_name(pod_name):
    """
    Normalizes pod name ONLY if it matches standard ReplicaSet pattern (hash-hash).
    Returns (workload_name, was_normalized).
    """
    if not pod_name:
        return "", False
    
    # Check strict RS pattern: name-hash-hash
    match = STRICT_RS_POD_RE.search(pod_name)
    if match:
        # Strip both suffixes to get workload name
        # e.g. api-7f8c9d5d6b-xfw2z -> api
        # match.start() gives index where the suffixes start
        return pod_name[:match.start()], True
        
    return pod_name, False

def calculate_fingerprint(alert):
    """
    Computes a deterministic v1 fingerprint for an alert.
    Returns (fingerprint_string, explanation_dict).
    """
    labels = alert.get("labels", {})
    alertname = labels.get("alertname", "Unknown")
    namespace = labels.get("namespace", "__none__")
    
    # 1. Determine Scope & Stable Identifiers
    scope = "global"
    entity_type = ""
    entity_value = ""
    
    # Check priorities
    # Explicit controller keys
    controller = (
        labels.get("deployment") or 
        labels.get("statefulset") or 
        labels.get("daemonset") or 
        labels.get("workload") or 
        labels.get("controller")
    )
    
    node = labels.get("node")
    pod = labels.get("pod")
    
    # Canonical inputs dict (sorted keys for hashing)
    inputs = {"alertname": alertname}
    
    if node:
        # Node-level
        scope = "node"
        entity_type = "node"
        entity_value = node
        inputs["node"] = node
    
    elif controller:
        # Workload-level (Explicit identifier)
        scope = "workload"
        entity_type = "workload"
        entity_value = f"{namespace}/{controller}"
        inputs["namespace"] = namespace
        inputs["controller"] = controller
        
    elif pod:
        # Pod-level logic
        normalized_name, was_normalized = _normalize_pod_name(pod)
        
        if was_normalized:
            # It matched RS pattern -> Treat as Workload (implied)
            # But stick to 'pod' scope if we want to distinguish, 
            # OR user said: "if derivation available... prefer workload?"
            # User said: "derived from pod ONLY when RS pattern matches"
            # It implies we use the base name as the grouping key.
            scope = "workload" # It's effectively a workload grouping now
            entity_type = "derived_workload"
            entity_value = f"{namespace}/{normalized_name}"
            inputs["namespace"] = namespace
            inputs["derived_workload"] = normalized_name
        else:
            # Specific Pod (StatefulSet logic or unique pod)
            scope = "pod"
            entity_type = "pod"
            entity_value = f"{namespace}/{pod}"
            inputs["namespace"] = namespace
            inputs["pod"] = pod
        
    else:
        # Global
        pass
        
    # 2. Build Explanation
    explanation = {
        "fingerprint_version": "v1",
        "scope": scope,
        "alertname": alertname,
        "namespace": namespace,
        "entity_type": entity_type,
        "entity_value": entity_value,
        "inputs": inputs
    }
    
    # 3. Compute Hash
    # Sort keys to ensure determinism
    canonical_string = json.dumps(inputs, sort_keys=True, separators=(',', ':'))
    hash_digest = hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
    
    fingerprint = f"v1:{hash_digest}"
    
    return fingerprint, explanation
