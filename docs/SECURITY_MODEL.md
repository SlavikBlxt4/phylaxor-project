# Security Model — Phylaxor

This document defines Phylaxor's **security boundaries** and **RBAC principles** to ensure enterprise-ready behavior.

## Core Principles

### 1. No Secrets by Default
- Phylaxor must **NOT** read Kubernetes Secrets
- If future features require secret access, require explicit Helm value + security review
- Rationale: Secrets can expose credentials, API keys, and sensitive configuration

### 2. Explicit Log Access
- Logs often contain sensitive data (request bodies, credentials, internal IPs, stack traces)
- Pod log access must be **opt-in** (default `PHYLAXOR_LOGS_MODE=none`)
- When enabled, must be justified and scoped (e.g., `podlogs` only in dev/labs)
- Rationale: Reduce attack surface and data exposure risk

### 3. Graceful Degradation on RBAC Failures
- If enricher is denied `pods/log` (403), it **logs a warning** but continues
- Pipeline must **NOT break** due to RBAC denials
- Rationale: Resilience; better to have partial context than fail completely

### 4. Separation of Duties
- **Cluster-aware components** (enricher, decision) can have kube/log perms but **no outbound Internet**
- **Notifier** (Telegram/HTTP) has **no Kubernetes permissions**
- Rationale: Limit blast radius if a component is compromised

### 5. Minimum RBAC Principle
- Every component gets only the minimum permissions required for its function
- Never grant `admin`, `cluster-admin`, or overly broad roles
- Review permissions quarterly or after feature additions

## RBAC by Component

### ingest
```
No Kubernetes permissions required.
- HTTP endpoint only
- No cluster access
- No Secret access
```

### enricher
```
Required Kubernetes permissions (baseline observer):
  - get, list pods (in namespace)
  - get, list nodes (cluster-wide)
  - get, list events (in namespace)
  - get, list namespaces (cluster-wide, for context)
  - get, list storageclass (cluster-wide, for storage context)

Optional (conditional on PHYLAXOR_LOGS_MODE):
  - get pods/log (IN NAMESPACE ONLY, if PHYLAXOR_LOGS_MODE=podlogs)

Explicitly denied:
  - Access to Secrets
  - Write permissions (read-only)
  - Outbound Internet (via NetworkPolicy if available)
```

### decision
```
Required permissions:
  - Read-only access to Postgres decision/KB tables

Explicitly denied:
  - Kubernetes API access (no kube perms needed)
  - Outbound Internet except Postgres connection
```

### notifier
```
EXPLICITLY NO Kubernetes permissions:
  - Must not be able to read pods, events, nodes, namespaces
  - Must not be able to access logs
  - Must not be able to read Secrets

Required permissions:
  - Outbound HTTPS to Telegram API (telegram.org)
  - Read-only access to Postgres decision table

Rationale: Limits damage if compromised (cannot access cluster data).
```

### feedback-gateway
```
Required permissions:
  - Write access to Postgres feedback table
  - Read access to Postgres decisions table (to validate decision_id)

Explicitly denied:
  - Kubernetes API access
  - Internet access except callback to Telegram (if bidirectional)
```

## RBAC Templates (Helm)

See `phylaxor-gitops/docs/RBAC_MODEL.md` for how to implement conditional RBAC in Helm.

**Key principle**: Use Helm values to enable/disable pod/log permission based on `logs.mode`.

```yaml
# Pseudocode (not actual Helm)
serviceAccount:
  name: phylaxor-enricher

# Conditional role binding: add pods/log only if podlogs mode
{{- if eq .Values.logging.mode "podlogs" }}
additionalPermissions:
  - apiGroups: [""]
    resources: ["pods/log"]
    verbs: ["get"]
{{- end }}
```

## OpenShift vs Minikube RBAC Differences

### Minikube
- More permissive by default
- RBAC enforcement is less strict
- Useful for rapid iteration and testing
- **Does not validate enterprise constraints**

### OpenShift CRC
- Strict RBAC enforcement
- Denies `pods/log` unless explicitly granted
- Enforces security context, network policies, SCCs
- **Validates that Phylaxor works in production-like environments**

**Testing implication**: Always test on CRC with `PHYLAXOR_LOGS_MODE=podlogs` to catch RBAC issues early.

## Secret Management (Future-Proofing)

### Current (MVP)
- No Secrets accessed
- Credentials (e.g., Loki auth) passed as environment variables or ConfigMaps
- No special secret handling required

### Future (If Needed)
If a feature requires secret access:

1. **Document the requirement** in `docs/SECURITY_MODEL.md`
2. **Add explicit Helm value** (e.g., `secrets.enabled: false` default)
3. **Require security review** before enabling
4. **Use least-privilege RBAC** (read only the Secret needed)
5. **Add warning** in logs when secret access is enabled

Example (placeholder):
```yaml
# This would be a FUTURE addition, not current
secrets:
  enabled: false  # Disabled by default
  # If enabled, enricher can read specific secrets for Loki auth
```

## NetworkPolicy (Optional, Recommended for Enterprise)

While not implemented in MVP, consider these policies for enterprise deployments:

### Enricher NetworkPolicy
```yaml
# Allows:
# - Inbound from decision/feedback-gateway
# - Outbound to Kubernetes API (internal)
# - Outbound to Redis (internal)
# - Outbound to Postgres (internal)
# - Outbound to Loki (if enabled)
# Denies: outbound to arbitrary external IPs
```

### Notifier NetworkPolicy
```yaml
# Allows:
# - Inbound from decision
# - Outbound to Telegram API (telegram.org)
# - Outbound to Postgres (internal)
# Denies: outbound to Kubernetes API, cluster internals
```

## Audit & Monitoring

### What to Monitor
- RBAC 403 errors in enricher logs (may indicate misconfiguration)
- Attempts to read Secrets (should never happen)
- Notifier outbound connections (should only be Telegram)
- Enricher outbound connections (should not reach external IPs)

### What NOT to Monitor
- Normal Redis/Postgres connections (internal, expected)
- Kubernetes API calls to observer resources (expected for enricher)
- Successful log reads (expected when enabled)

## OpenShift-Specific Constraints

### Security Context Constraints (SCC)
- Phylaxor services run under permissive or restricted SCC
- Do not require `privileged` SCC
- Do not require special capabilities

### Service Account Links
- Each component has its own ServiceAccount (not default)
- ServiceAccount has explicit ClusterRole binding
- ClusterRoleBinding scoped to namespace

### Loki Integration (Future)
- Loki must be deployed in `openshift-logging` namespace
- Phylaxor uses service-to-service auth (e.g., bearer token via ConfigMap)
- Network policies between `phylaxor` and `openshift-logging` namespaces

## Incident Response: If Compromised

### If enricher is compromised
- **Limited damage**: Can read pods/events/nodes but no Secrets
- **Immediate action**: Revoke ServiceAccount tokens, restart enricher
- **Investigation**: Audit API server logs for unauthorized queries

### If notifier is compromised
- **Limited damage**: Can send Telegram messages; no cluster access
- **Immediate action**: Revoke Telegram bot token, restart notifier
- **Investigation**: Check Telegram API logs for message history

## Checklist for RBAC Review

- [ ] Every ServiceAccount has explicit ClusterRole (no default SA)
- [ ] Every ClusterRole lists only needed resources (no wildcards)
- [ ] `notifier` has zero Kubernetes permissions
- [ ] `enricher` does not have Secret read permission
- [ ] `pods/log` permission only granted if `PHYLAXOR_LOGS_MODE=podlogs`
- [ ] All RBAC changes documented in `phylaxor-gitops/docs/RBAC_MODEL.md`
- [ ] Tested on OpenShift CRC (strict mode)
- [ ] NetworkPolicy applied (if available in target environment)

## Related Documents

- **`docs/CONTRACT_ENV.md`** — Configuration contract (logging modes, defaults)
- **`docs/LOGGING_MODES.md`** — Logging mode analysis and risks
- **`phylaxor-gitops/docs/RBAC_MODEL.md`** — Helm implementation of RBAC templates
