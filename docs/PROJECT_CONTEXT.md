# Project Context — Phylaxor

This is the canonical **global context** document for Phylaxor. All contributors and AI agents (including Copilot) should read this first.

## What is Phylaxor

Phylaxor is a microservice-based **AI SRE Agent for Kubernetes / OpenShift** that automates incident response:

1. **Consumes** alerts from Alertmanager (webhook)
2. **Enriches** with cluster context (pods, events, logs, metrics)
3. **Applies** knowledge-base rules and historical decisions
4. **Notifies** on-call engineers (Telegram) with actionable troubleshooting steps
5. **Collects** feedback (thumbs up/down) to improve recommendations

**Goal**: Reduce MTTR (Mean Time To Resolution) by providing context-aware, repeatable incident responses.

## Target Environments

- **Kubernetes vanilla** (dev/labs): Minikube
- **OpenShift enterprise** (dev/labs): CRC (CodeReady Containers)

Primary focus: **enterprise-ready behavior for OpenShift** (strict RBAC, security-first, defensible design).

## High-Level Architecture

See `ARCHITECTURE.md` for detailed flow and ASCII diagrams.

**Simplified flow**:
```
Alertmanager → ingest → Redis → enricher → Redis → decision → notifier (Telegram)
                                                      ↓
                                                  Postgres (decisions, KB, feedback)
```

## Current System State

### Working Components
- ✅ Feedback gateway: Telegram callback buttons → Postgres
- ✅ Decision engine: KB matching + historical lookup
- ✅ Enricher: cluster context + pod status + events
- ✅ Ingest: alert normalization → Redis
- ✅ Notifier: Telegram integration

### Known Issue
**OpenShift RBAC limitation**: Reading pod logs via Kubernetes API (`pods/log`) fails with 403 unless explicitly granted via ClusterRole.

This drives the **logging modes** strategy (see `docs/CONTRACT_ENV.md`).

## Security Posture

### Non-Negotiables
1. **No Secrets by default** — Do not read Kubernetes Secrets
2. **Explicit opt-in for log access** — Logs may contain sensitive data
3. **Graceful degradation** — RBAC 403 errors do NOT break the pipeline
4. **Separation of duties** — Notifier has NO kube/log permissions
5. **Minimum RBAC principle** — Only grant what is strictly needed

### OpenShift vs Minikube
- **OpenShift CRC**: Strict RBAC enforcement (security testing ground)
- **Minikube**: Permissive by default (fast iteration)

## Configuration Contract (MVP)

Environment variables control behavior (see `docs/CONTRACT_ENV.md`):

- `PHYLAXOR_LOGS_MODE` — `none` | `loki` | `podlogs` (default: `none`)
- `PHYLAXOR_EVENTS_ENABLED` — `true` | `false` (default: `true`)
- `PHYLAXOR_LOGS_MAX_LINES`, `PHYLAXOR_LOGS_MAX_BYTES`, `PHYLAXOR_LOGS_LOOKBACK`
- Loki settings (endpoint, tenant, auth) — placeholder for future

**Why env vars first?** Simple, testable, and avoid CRDs/operators for now.

## Logging Modes Explained

See `docs/LOGGING_MODES.md` for deep dive.

| Mode | Source | Risk | Use Case |
|------|--------|------|----------|
| `none` | Events + resource status only | None (no logs read) | Default, safest |
| `loki` | Centralized logging backend | Low (enterprise-recommended) | OpenShift Logging / LokiStack |
| `podlogs` | Kubernetes API `pods/log` | High (logs can leak secrets) | Manual fallback if Loki unavailable |

## Testing Strategy

We validate 3 end-to-end scenarios:

1. **mode=none**: Alert → Recommendation without logs (no RBAC issues)
2. **mode=loki**: Alert → Recommendation with centralized logs (requires Loki setup)
3. **mode=podlogs**: Alert → Recommendation with pod logs (requires explicit RBAC grant + warning)

See `docs/TEST_MATRIX.md` for acceptance criteria.

## Immediate Next Steps

1. ✅ Define the env var contract (this doc + `CONTRACT_ENV.md`)
2. ⏳ Update enricher to switch behavior based on `PHYLAXOR_LOGS_MODE`
3. ⏳ Add RBAC templates in Helm for conditional log permissions
4. ⏳ Implement Loki provider and test on CRC
5. ⏳ Add E2E tests for all 3 modes

## Key Constraints

- Project is **microservices + Deployments** (not CRDs/operators yet)
- Goal: Reach an **MVP that is launchable** without security concerns
- Must be testable on **both Minikube and OpenShift CRC**

## References

- **`ARCHITECTURE.md`** — Component details and flow
- **`docs/CONTRACT_ENV.md`** — Complete env var specification
- **`docs/SECURITY_MODEL.md`** — RBAC and security boundaries
- **`docs/LOGGING_MODES.md`** — Detailed logging mode analysis
- **`docs/TEST_MATRIX.md`** — E2E test scenarios and checklist
