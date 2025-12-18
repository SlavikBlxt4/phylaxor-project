# Logging Modes — Deep Dive

This document provides detailed analysis of Phylaxor's three logging modes: **`none`**, **`loki`**, and **`podlogs`**. Understanding the trade-offs is critical for choosing the right mode for your environment.

## Why Multiple Modes?

Phylaxor needs cluster context to produce good recommendations. Logs are valuable context but present security risks:

1. **Logs often contain secrets** — API keys, passwords, tokens, connection strings
2. **Logs can expose internal details** — Architecture, IPs, service names, stack traces
3. **Kubernetes pod/log access is not granular** — You either grant it or don't (no per-pod filtering)
4. **Centralized logging (Loki) is safer** — One place to enforce access control

**Strategy**: Offer a choice (none/loki/podlogs) so teams can pick the right risk/capability trade-off.

## Mode: `none` (Default, Safest)

### What Enricher Does
```
Fetch context WITHOUT logs:
  • Cluster version and node summary
  • Pod status (phase, restart count, condition)
  • Node capacity and allocations
  • Cluster events (pod/node/deployment changes)
  • Storage class info
```

### Risks
✅ **None** — No log content is fetched or transmitted.

### Capabilities
- Enricher can still produce useful recommendations based on:
  - Alert name/labels/severity
  - Pod/node state
  - Recent cluster events
  - Historical decisions (KB rules)
- Works in all environments (no Loki/pods/log RBAC needed)

### RBAC Required
```
Baseline observer permissions:
  • get, list pods
  • get, list nodes
  • get, list events
  • get, list namespaces
  • get, list storageclass
```

### Use Cases
- ✅ Development environments (Minikube) → fastest iteration
- ✅ Sensitive environments where log exposure is unacceptable
- ✅ First deployment in a new cluster (baseline safe mode)
- ✅ When Loki is not available and pods/log RBAC is not granted

### Example Configuration
```bash
PHYLAXOR_LOGS_MODE=none
PHYLAXOR_EVENTS_ENABLED=true
```

### Limitations
- Enricher cannot surface actual error logs (only context)
- May miss root cause if problem is in error output (not event)
- Decision engine relies more on historical KB rules

---

## Mode: `loki` (Recommended for Enterprise)

### What Enricher Does
```
Fetch context WITH centralized logs:
  • All context from mode=none
  • Query Loki backend for pod logs
  • Include relevant log snippet in enriched event
```

### Prerequisites
- **OpenShift Logging** or **Grafana Loki** deployed in cluster
- Loki query API accessible from enricher pod (usually in same cluster)
- Enricher configured with Loki endpoint, tenant ID, auth credentials

### RBAC Required
```
Same baseline observer permissions as mode=none:
  • get, list pods
  • get, list nodes
  • get, list events
  • get, list namespaces
  • get, list storageclass

Note: NO pods/log permission needed (logs come from Loki, not API)
```

### Architecture
```
enricher (in phylaxor namespace)
    │
    ├─→ Kubernetes API (observer roles)
    │   └─→ pods, nodes, events, storage
    │
    └─→ Loki API (https://loki.logging.svc.cluster.local:3100)
        └─→ query pod logs (via LogQL)
            └─→ Stored in openshift-logging namespace
```

### Risks
⚠️ **Low** — Loki controls access via:
- Tenant ID (logical isolation)
- Authentication (username/password or bearer token)
- Loki's own RBAC (who can query which namespaces/pods)

If Loki is breached, logs are exposed; but Phylaxor itself doesn't hold log access risk.

### Capabilities
- Full context: pod status + relevant error logs
- Recommendations can pinpoint root cause from logs
- Logs stored centrally (easier audit trail)

### Use Cases
- ✅ OpenShift enterprise environments
- ✅ Any environment with centralized logging (ELK, Splunk, Datadog)
- ✅ When you want log context but don't want to grant pods/log RBAC to Phylaxor

### Future Implementation
**Status**: Placeholder in MVP. Implementation order:

1. Define Loki query interface (LogQL patterns for pod selection)
2. Implement Loki client (HTTP + auth)
3. Test on CRC with OpenShift Logging
4. Add Loki setup documentation for CRC

### Example Configuration (Future)
```bash
PHYLAXOR_LOGS_MODE=loki
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOKI_ENDPOINT=https://loki.logging.svc.cluster.local:3100
PHYLAXOR_LOKI_TENANT_ID=phylaxor
PHYLAXOR_LOKI_USERNAME=phylaxor-user
PHYLAXOR_LOKI_PASSWORD=<secret-from-k8s-secret>
PHYLAXOR_LOGS_MAX_LINES=200
PHYLAXOR_LOGS_LOOKBACK=600
```

### Limitations
- Requires Loki to be deployed and functional
- Enricher latency depends on Loki query performance
- Loki logs older than retention window are unavailable

---

## Mode: `podlogs` (Manual Fallback, Higher Risk)

### What Enricher Does
```
Fetch context WITH pod logs (direct API):
  • All context from mode=none
  • Use Kubernetes API pods/log endpoint to fetch logs
  • Include log snippet in enriched event
  • Handle RBAC 403 gracefully (log warning, continue)
```

### RBAC Required
```
Baseline observer permissions (same as mode=none) PLUS:
  • get pods/log (in namespace only)
    Example ClusterRole rule:
      apiGroups: [""]
      resources: ["pods/log"]
      verbs: ["get"]
```

### RBAC Failure Mode
```
If RBAC 403 occurs:
  1. Enricher logs: "WARN: pods/log denied for pod X in namespace Y"
  2. Enricher continues WITHOUT logs
  3. Pipeline does NOT fail
  4. Enriched event pushed to Redis (without log snippet)
```

**Rationale**: Pipeline resilience; better partial context than failure.

### Risks
⚠️ **High** — Logs may contain sensitive data:

| Content | Risk | Example |
|---------|------|---------|
| Request bodies | High | API payloads, SQL queries, form data |
| Error messages | Medium | Stack traces, internal IPs, service names |
| Configuration | Medium | Hostnames, environment details |
| Authentication | High | Bearer tokens, API keys (if accidentally logged) |
| PII | High | User IPs, usernames, email addresses |

**Important**: This mode should be disabled by default and enabled only after:
- [ ] Risk assessment by security team
- [ ] Confirmation that logs do NOT contain secrets
- [ ] Audit trail enabled (Kubernetes API server logging)

### Capabilities
- Direct pod log access (no Loki needed)
- Useful for quick debugging in dev/lab environments
- Fastest time-to-value (no extra infrastructure)

### Use Cases
- ✅ Development environments (Minikube) → fast feedback loop
- ✅ Lab environments where log content is known to be non-sensitive
- ✅ Testing Phylaxor RBAC behavior (to catch permission issues)
- ❌ Production or multi-tenant environments
- ❌ When pod logs may contain user data or secrets

### How OpenShift Denies `pods/log`

**Scenario**: You try to enable `podlogs` on OpenShift CRC without granting the permission.

```
enricher startup:
  1. Receives alert
  2. Attempts: GET /api/v1/namespaces/phylaxor/pods/vulnerable-app/log
  3. OpenShift API server responds: 403 Forbidden
     "cannot get resource "pods/log" in namespace "phylaxor" in the namespace phylaxor"
  4. Enricher logs warning and continues (graceful degradation)
  5. Enriched event published to Redis without log content
```

**Why this happens**: OpenShift default RBAC is restrictive. You must explicitly grant `pods/log` permission via ClusterRole.

### Example Configuration
```bash
PHYLAXOR_LOGS_MODE=podlogs
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOGS_MAX_LINES=200
PHYLAXOR_LOGS_LOOKBACK=600
PHYLAXOR_LOGS_MAX_BYTES=50000
```

### Limitations
- High security risk (logs can leak secrets)
- Not suitable for environments with sensitive data
- RBAC complexity (must grant pods/log permission)
- Enricher latency depends on pod log size

---

## Decision: Why Modes First Before CRDs/Operators?

**Question**: Why not implement this as a Kubernetes Operator or Custom Resource?

**Answer**: 

1. **Speed to MVP**: Env vars are simpler to test and iterate
2. **Fewer dependencies**: No CRD controller needed; just Deployments
3. **Clear contract**: Env var contract is easy to document and understand
4. **Future-proof**: Once stable, can be wrapped in Operator later
5. **Testability**: Easy to test different modes by changing deployment env vars

**Roadmap**:
- ✅ MVP: Env vars (current)
- ⏳ Future: CRD-based config (if project matures)

---

## Comparison Table

| Aspect | `none` | `loki` | `podlogs` |
|--------|--------|--------|----------|
| **Risk** | None | Low | High |
| **RBAC Complexity** | Low | Low | Medium |
| **Infrastructure** | Just Phylaxor | Phylaxor + Loki | Just Phylaxor |
| **Recommendation Quality** | Good | Excellent | Excellent |
| **Log Freshness** | N/A | Depends on Loki | Real-time |
| **Suited for** | Dev/sensitive | Enterprise | Dev/test labs |
| **Default** | ✅ Yes | ❌ No | ❌ No |
| **Requires pods/log RBAC** | No | No | Yes |

---

## Testing Strategy

For each mode, test end-to-end on **both Minikube and CRC**:

### Test: mode=none
```
1. Deploy enricher with PHYLAXOR_LOGS_MODE=none
2. Send alert
3. Verify: enriched event has context but NO logs
4. Verify: recommendation is generated (may have lower confidence)
5. Pass: Pipeline succeeds without RBAC issues
```

### Test: mode=loki (Minikube + CRC)
```
1. Deploy Loki (or use existing LokiStack in CRC)
2. Configure enricher with PHYLAXOR_LOKI_ENDPOINT and auth
3. Send alert
4. Verify: enriched event includes log snippet from Loki
5. Verify: recommendation includes log-based insights
6. Pass: Pipeline succeeds; logs fetched centrally
```

### Test: mode=podlogs (Minikube)
```
1. Deploy enricher with PHYLAXOR_LOGS_MODE=podlogs
2. Send alert
3. Verify: enriched event includes pod logs (direct API)
4. Pass: Pipeline succeeds with pod logs
```

### Test: mode=podlogs + RBAC 403 (CRC)
```
1. Deploy enricher with PHYLAXOR_LOGS_MODE=podlogs
2. DO NOT grant pods/log RBAC permission
3. Send alert
4. Verify: enricher logs warning about 403
5. Verify: pipeline continues (graceful degradation)
6. Verify: enriched event published WITHOUT log content
7. Pass: RBAC failure handled correctly
```

See `docs/TEST_MATRIX.md` for full acceptance criteria.

---

## Related Documents

- **`docs/CONTRACT_ENV.md`** — Env var specification
- **`docs/SECURITY_MODEL.md`** — Security boundaries and RBAC
- **`docs/TEST_MATRIX.md`** — Full test scenarios
- **`ARCHITECTURE.md`** — Enricher component details
