# Alert Fingerprinting and Decision History Scoring

This document describes the implementation of two key reliability features in Phylaxor: **Alert Fingerprinting** for deterministic grouping, and **History Scoring** for gating the usage of past automated decisions.

## 1. Alert Fingerprinting (v1)

Fingerprinting solves the problem of unstable or upstream-dependent alert identification. Phylaxor now computes its own deterministic fingerprint for every alert.

### Logic
The fingerprint (`v1:<sha256>`) is derived from a priority-based selection of stable inputs:

1.  **Node Scope**: If `node` label exists -> `alertname + node_name`.
2.  **Workload Scope**:
    -   If controller label (`deployment`, `statefulset`, etc.) exists -> `alertname + namespace + controller_name`.
    -   If `pod` name follows a strict ReplicaSet pattern (e.g., `api-7f8c9d...`) -> derives workload name -> `alertname + namespace + derived_workload`.
3.  **Pod Scope** (Fallback): Explicit pod reference (e.g., StatefulSet `redis-0`) -> `alertname + namespace + pod_name`.
4.  **Global Scope**: Default -> `alertname`.

### Key Features
-   **Normalization**: Automatically strips ephemeral ReplicaSet hashes from pod names to ensure `api-xh52z` and `api-9k21a` map to the same fingerprint.
-   **Denylist**: Explicitly ignores volatile labels like `resourceVersion`, `pod_uid`, and `instance` (IPs).
-   **Explainability**: Every ingest log includes a `fingerprint_explanation` dict detailing exactly which scope and entities were used.

---

## 2. Decision History Scoring

To prevent "feedback loops" where Phylaxor blindly repeats past mistakes, historical decisions are now strictly gated.

### The Algorithm
Before reusing a historical decision, the system fetches the last **20** decisions for the alert's fingerprint and runs them through a scoring engine (`services/decision/history_score.py`).

### Eligibility Criteria
A history match is considered valid **only if ALL** the following conditions are met:

1.  **Minimum Samples**: At least **3** valid previous decisions exist.
2.  **Freshness**:
    -   Decisions older than **30 days** are discarded.
    -   If all available history is too old, the system explicitly returns `all_history_too_old` and forces a fresh KB lookup.
3.  **Consensus**:
    -   At least **60%** of the valid history must agree on the Recommendation.
    -   **Stable Grouping**: Grouping prefers `kb_id` or `rule_id` (if available) over text summaries, making it robust against minor wording changes.
4.  **Quality Score (Threshold 85/100)**:
    -   **Base**: Time-weighted average of past confidence scores (Half-life: 14 days).
    -   **Penalty**: A weighted variance penalty is subtracted. High inconsistency in past confidence lowers the final score significantly.

### Decision Selection
If eligible, the system does **not** simply pick the most recent decision. Instead, it selects the recommendation with the **highest weighted support** (sum of recency weights), ensuring the "most trusted" answer wins over a potentially anomalous recent outlier.

## Database Integration
-   **Alerts Table**: Indexed on `fingerprint`.
-   **Decisions Table**: Uses `kb_id`, `rule_id`, and `confidence` to drive the scoring logic.
