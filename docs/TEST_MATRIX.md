# Test Matrix — Phylaxor E2E Scenarios

This document defines acceptance criteria for end-to-end testing of Phylaxor across all logging modes and environments.

## Current Validation Status

Already validated:
- core flow `alert -> ingest -> enricher -> decision -> brain-gateway -> notifier -> Telegram`
- persistence of AI-backed decisions in `decisions`
- persistence of AI request metadata in `ai_usage`
- real alert delivery through OpenShift Alertmanager using a synthetic `PrometheusRule`

Reference script:
- `phylaxor-gitops/e2e_brain_gateway.sh`
- `phylaxor-gitops/e2e_alertmanager_openshift.sh`

## Test Environments

| Environment | PHYLAXOR_LOGS_MODE | Use Case |
|-------------|-------------------|----------|
| Minikube (default) | `none` | Fastest dev iteration |
| Minikube (optional) | `podlogs` | Test graceful degradation |
| OpenShift CRC | `none` | Validate tight RBAC |
| OpenShift CRC | `podlogs` + RBAC 403 | Test RBAC denial handling |
| OpenShift CRC | `loki` | Enterprise path (future) |

---

## Test Scenario 1: mode=none (All Environments)

**Goal**: Verify Phylaxor works safely without log access.

### Setup
```bash
PHYLAXOR_LOGS_MODE=none
PHYLAXOR_EVENTS_ENABLED=true
```

### RBAC Configuration
- Enricher: Baseline observer role (no pods/log)
- Notifier: No Kubernetes permissions

### Test Steps

#### 1.1 Alert Ingestion
- [ ] Send alert to ingest HTTP endpoint
- [ ] Verify: Alert appears in Redis `phylaxor_raw` list
- [ ] Verify: Alert has normalized format (alertname, labels, etc.)

#### 1.2 Enrichment
- [ ] Enricher processes alert from Redis
- [ ] Verify: Context fetched (cluster version, pod status, events)
- [ ] Verify: NO log content attempted
- [ ] Verify: Enriched event in Redis `phylaxor_enriched`
- [ ] Verify: RBAC logs are clean (no 403 errors for pods/log)

#### 1.3 Decision Engine
- [ ] Decision reads enriched event from Redis
- [ ] Verify: KB matching attempted
- [ ] Verify: Historical lookup executed (Postgres)
- [ ] Verify: Recommendation generated with confidence/reasoning
- [ ] Verify: Decision record in Postgres `decisions` table

#### 1.4 Notification
- [ ] Notifier reads decision from Redis
- [ ] Verify: Telegram message sent (if configured)
- [ ] Verify: Message includes context (pod name, alerts, cluster)
- [ ] Verify: Interactive buttons present (thumbs up/down)

#### 1.5 Feedback Loop
- [ ] Click feedback button in Telegram
- [ ] Verify: Callback webhook received by feedback-gateway
- [ ] Verify: Vote recorded in Postgres `feedback` table
- [ ] Verify: decision_id and vote (true/false) correct

### Acceptance Criteria
- ✅ All steps 1.1–1.5 complete without error
- ✅ No RBAC 403 errors in logs
- ✅ Pipeline latency < 10 seconds (ingest to Telegram)
- ✅ At least one KB rule or fallback recommendation generated
- ✅ Feedback vote recorded in Postgres

### Pass/Fail
- **PASS**: All criteria met on both Minikube and CRC
- **FAIL**: Any step fails or latency exceeds threshold

---

## Test Scenario 2: mode=loki (OpenShift CRC, Future)

**Goal**: Verify logs fetched from centralized backend.

**Status**: Placeholder. Implementation pending.

### Prerequisites
- [ ] LokiStack deployed in OpenShift Logging namespace
- [ ] Enricher ServiceAccount can authenticate to Loki (bearer token or basic auth)
- [ ] Sample pod logs available in Loki (e.g., from app pods)

### Setup
```bash
PHYLAXOR_LOGS_MODE=loki
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOKI_ENDPOINT=https://loki.logging.svc.cluster.local:3100
PHYLAXOR_LOKI_TENANT_ID=phylaxor
PHYLAXOR_LOKI_USERNAME=phylaxor-user
PHYLAXOR_LOKI_PASSWORD=<from-secret>
PHYLAXOR_LOGS_MAX_LINES=200
PHYLAXOR_LOGS_LOOKBACK=600
```

### RBAC Configuration
- Enricher: Baseline observer role (no pods/log)
- Loki RBAC: Phylaxor can query logs from phylaxor namespace

### Test Steps

#### 2.1 Loki Connectivity
- [ ] Enricher resolves Loki endpoint DNS
- [ ] Verify: HTTPS connection established (TLS valid)
- [ ] Verify: Authentication succeeds (bearer token or basic auth)
- [ ] Verify: Enricher logs show successful Loki auth

#### 2.2 Alert with Logs
- [ ] Send alert for pod in phylaxor namespace
- [ ] Trigger pod to produce error/warning logs
- [ ] Enricher processes alert
- [ ] Verify: Loki queried with pod selector
- [ ] Verify: Log lines retrieved (200 lines max)
- [ ] Verify: Enriched event includes log snippet

#### 2.3 Recommendation with Log Context
- [ ] Decision engine receives enriched event with logs
- [ ] Verify: KB matching considers log content
- [ ] Verify: Recommendation confidence higher than mode=none
- [ ] Verify: Recommendation includes log excerpt in reasoning

#### 2.4 Loki Fallback (Query Timeout)
- [ ] Artificially delay Loki response (or disconnect)
- [ ] Enricher processes alert
- [ ] Verify: Enricher retries or times out gracefully
- [ ] Verify: Pipeline continues WITHOUT logs (degrades)

### Acceptance Criteria
- ✅ Loki connectivity verified
- ✅ Log lines retrieved and included in enriched event
- ✅ Recommendation generated with higher confidence than mode=none
- ✅ Graceful degradation on Loki failure
- ✅ No Kubernetes pods/log RBAC issues

### Pass/Fail
- **PASS**: All criteria met (Loki available and responsive)
- **SKIP**: Loki not deployed (acceptable for MVP)
- **FAIL**: Loki failure breaks pipeline (should degrade gracefully)

---

## Test Scenario 3: mode=podlogs (Minikube)

**Goal**: Verify direct pod log access works on permissive environment.

### Setup
```bash
PHYLAXOR_LOGS_MODE=podlogs
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOGS_MAX_LINES=200
PHYLAXOR_LOGS_LOOKBACK=600
```

### RBAC Configuration
- Enricher: Baseline observer + `pods/log` permission
- Minikube: Permissive (should grant easily)

### Test Steps

#### 3.1 RBAC Setup
- [ ] Create ServiceAccount for enricher
- [ ] Grant `pods/log` permission via ClusterRole
- [ ] Verify: RBAC binding in `kubectl get rolebindings`
- [ ] Verify: ServiceAccount can call `kubectl logs <pod>` (if tested manually)

#### 3.2 Alert with Pod Logs
- [ ] Send alert for pod with available logs
- [ ] Enricher processes alert
- [ ] Verify: Kubernetes API queried for pods/log
- [ ] Verify: Log lines retrieved (200 lines max, within 10 min lookback)
- [ ] Verify: Enriched event includes log content
- [ ] Verify: Log size < PHYLAXOR_LOGS_MAX_BYTES

#### 3.3 Recommendation with Pod Logs
- [ ] Decision engine receives enriched event with logs
- [ ] Verify: Recommendation generated with pod log insights
- [ ] Verify: Confidence and reasoning reflect log content

### Acceptance Criteria
- ✅ RBAC permission granted and verified
- ✅ Pod logs retrieved successfully
- ✅ Enriched event size reasonable (< 1 MB)
- ✅ Pipeline succeeds end-to-end

### Pass/Fail
- **PASS**: All criteria met on Minikube
- **FAIL**: RBAC or log retrieval fails

---

## Test Scenario 4: mode=podlogs + RBAC 403 (OpenShift CRC)

**Goal**: Verify graceful degradation when pods/log RBAC denied.

### Setup
```bash
PHYLAXOR_LOGS_MODE=podlogs
PHYLAXOR_EVENTS_ENABLED=true
```

### RBAC Configuration
- Enricher: Baseline observer role (intentionally NO pods/log)
- CRC: Strict enforcement (will deny pods/log)

### Test Steps

#### 4.1 RBAC Verification
- [ ] Verify: ClusterRole does NOT include `pods/log`
- [ ] Verify: Manual `kubectl logs` attempt fails with 403
- [ ] Verify: Error message confirms pods/log denial

#### 4.2 Alert Processing with Expected RBAC Failure
- [ ] Send alert
- [ ] Enricher attempts to fetch logs
- [ ] Verify: Kubernetes API returns 403
- [ ] Verify: Enricher logs **WARN** message about pods/log denied
  - Expected log: "WARN: pods/log denied for pod X in namespace Y"
  - Must NOT exit or crash

#### 4.3 Graceful Degradation
- [ ] Verify: Enricher continues processing
- [ ] Verify: Enriched event pushed to Redis (without logs)
- [ ] Verify: Pipeline continues (decision engine processes event)
- [ ] Verify: Decision and notification generated (with degraded context)

#### 4.4 Log Analysis
- [ ] Grep enricher logs for 403 warnings
- [ ] Verify: One warning per attempted pod log fetch
- [ ] Verify: No errors or stack traces (WARN level, not ERROR)
- [ ] Verify: Subsequent alerts processed similarly

### Acceptance Criteria
- ✅ RBAC 403 handled without crash
- ✅ Enricher logs WARN message
- ✅ Pipeline continues (events pushed to Redis, decisions generated)
- ✅ Recommendation quality degraded but acceptable
- ✅ No stack traces or unhandled exceptions

### Pass/Fail
- **PASS**: RBAC 403 gracefully handled; pipeline continues
- **FAIL**: Pipeline breaks on RBAC 403 or enricher crashes

---

## Test Scenario 5: Cross-Mode Comparison (Optional)

**Goal**: Compare recommendation quality across modes.

### Setup
1. Deploy Phylaxor with mode=none (baseline)
2. Deploy second instance with mode=podlogs (Minikube)
3. Send same alert to both

### Comparison
| Metric | mode=none | mode=podlogs | Expected |
|--------|-----------|-----------|----------|
| Latency | Measured | Measured | podlogs ~0.5-2s slower (log fetch) |
| Recommendation confidence | Measured | Measured | podlogs higher if logs are relevant |
| Context depth | Limited | Full (logs) | podlogs should have richer context |
| RBAC surface | Low | Higher | podlogs needs pods/log |

### Acceptance Criteria
- ✅ mode=podlogs is not significantly slower (< 5x)
- ✅ Recommendations are consistent (same KB rules applied)
- ✅ Both modes produce valid recommendations

---

## Continuous Integration (CI) Checklist

For CI/CD pipeline:

### Pre-Merge Tests
- [ ] Test scenario 1 (mode=none) on Minikube
- [ ] RBAC configuration validates correctly (Helm templates)
- [ ] No new permissions granted by default
- [ ] Docker image builds successfully
- [ ] Unit tests pass (if added)

### Pre-Release Tests
- [ ] Test scenario 1 on CRC (mode=none)
- [ ] Test scenario 4 on CRC (mode=podlogs + 403)
- [ ] Manual smoke test (end-to-end: alert → Telegram)
- [ ] Log analysis confirms no 403 crashes

### Optional (Future)
- [ ] Test scenario 2 on CRC (mode=loki, if Loki available)
- [ ] Test scenario 3 on Minikube (mode=podlogs)
- [ ] Performance benchmarks (latency threshold)
- [ ] Security scan (RBAC audit)

---

## Test Data

### Alert Examples

#### Example 1: Pod CrashLoopBackOff
```json
{
  "alertname": "PodCrashLooping",
  "severity": "critical",
  "namespace": "default",
  "pod": "app-5d7c8f9b2",
  "status": "firing"
}
```
**Expected**: Recommendation to check logs or restart pod.

#### Example 2: Node NotReady
```json
{
  "alertname": "NodeNotReady",
  "severity": "critical",
  "node": "node-1",
  "status": "firing"
}
```
**Expected**: Recommendation to check node status, drain if needed.

#### Example 3: High Memory Usage
```json
{
  "alertname": "PodMemoryHigh",
  "severity": "warning",
  "namespace": "default",
  "pod": "api-server",
  "memory": "85%",
  "status": "firing"
}
```
**Expected**: Recommendation based on KB rules (restart, scale up, etc.).

---

## Test Results Template

```markdown
## Test Run: [Date] [Environment] [Mode]

- Environment: Minikube / CRC
- Mode: none / loki / podlogs
- Enricher RBAC: [baseline / +pods/log / -pods/log]

### Results
- [ ] 1.1 Alert Ingestion: PASS / FAIL / N/A
- [ ] 1.2 Enrichment: PASS / FAIL / N/A
- [ ] 1.3 Decision Engine: PASS / FAIL / N/A
- [ ] 1.4 Notification: PASS / FAIL / N/A
- [ ] 1.5 Feedback Loop: PASS / FAIL / N/A

### Notes
- Latency: X seconds (ingest to Telegram)
- Issues: [list any blockers]
- Recommendations: [improvements or next steps]

### Sign-off
- Tested by: [name]
- Date: [date]
```

---

## Related Documents

- **`docs/CONTRACT_ENV.md`** — Configuration contract
- **`docs/LOGGING_MODES.md`** — Logging mode analysis
- **`docs/SECURITY_MODEL.md`** — RBAC requirements
