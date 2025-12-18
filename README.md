# Phylaxor — Application Code

This is the application code repository for Phylaxor microservices.

For deployment (Helm charts, RBAC, ArgoCD apps), see `phylaxor-gitops/`.

## Project Structure

```
phylaxor-project/
  ├── ARCHITECTURE.md              # Component architecture and data flow
  ├── docs/
  │   ├── PROJECT_CONTEXT.md       # Global project context (canonical reference)
  │   ├── CONTRACT_ENV.md          # Environment variable contract
  │   ├── SECURITY_MODEL.md        # RBAC and security boundaries
  │   ├── LOGGING_MODES.md         # Logging mode analysis (none/loki/podlogs)
  │   └── TEST_MATRIX.md           # E2E test scenarios and acceptance criteria
  ├── .github/
  │   └── copilot-instructions.md  # AI agent instructions and non-negotiables
  ├── services/
  │   ├── ingest/                  # Alert ingestion (HTTP)
  │   ├── enricher/                # Alert enrichment with cluster context
  │   ├── decision/                # Recommendation engine (KB + history)
  │   ├── notifier/                # Telegram notification
  │   ├── feedback/                # Feedback dashboard
  │   ├── feedback_gateway/        # Telegram callback handler
  │   └── postgres/                # Database initialization
  ├── infra/
  │   └── postgres/
  │       └── init.sql             # Database schema
  └── docker-compose.yml           # Local development setup
```

## Global Context & Contract

**Before writing or modifying code, read these documents:**

1. **`ARCHITECTURE.md`** — How components communicate (Redis queues, Postgres storage)
2. **`docs/PROJECT_CONTEXT.md`** — Project goals, current state, immediate next steps
3. **`docs/CONTRACT_ENV.md`** — Environment variable contract (logging modes, feature flags, defaults)
4. **`docs/SECURITY_MODEL.md`** — RBAC requirements, non-negotiables, separation of duties
5. **`docs/LOGGING_MODES.md`** — Why we have `none`/`loki`/`podlogs` modes and when to use each
6. **`.github/copilot-instructions.md`** — Copilot instructions and coding guidelines

## Quick Start

### Local Development (Docker Compose)

```bash
# Start services (ingest, enricher, decision, notifier, postgres, redis)
docker-compose up -d

# Check logs
docker-compose logs -f enricher

# Stop
docker-compose down
```

### Configuration

Set environment variables (see `docs/CONTRACT_ENV.md`):

```bash
# Logging mode (default: none = safest)
export PHYLAXOR_LOGS_MODE=none

# Enable cluster events enrichment
export PHYLAXOR_EVENTS_ENABLED=true

# Log limits
export PHYLAXOR_LOGS_MAX_LINES=500
export PHYLAXOR_LOGS_MAX_BYTES=100000
export PHYLAXOR_LOGS_LOOKBACK=300
```

### Send a Test Alert

```bash
curl -X POST http://localhost:5000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "alerts": [{
      "status": "firing",
      "labels": {
        "alertname": "TestAlert",
        "severity": "warning"
      },
      "annotations": {
        "summary": "Test alert for Phylaxor"
      }
    }]
  }'
```

## Security Posture

### Non-Negotiables
- ✅ **No Secrets by default** — Do not read Kubernetes Secrets
- ✅ **Explicit log access** — Logs are opt-in; default mode is `none`
- ✅ **Graceful degradation** — RBAC 403 errors do not break the pipeline
- ✅ **Separation of duties** — Notifier has NO Kubernetes permissions
- ✅ **Minimum RBAC** — Every component gets only what it needs

See `docs/SECURITY_MODEL.md` for detailed RBAC requirements.

## Testing

### E2E Test Scenarios

See `docs/TEST_MATRIX.md` for full acceptance criteria.

**Quick tests**:

```bash
# Test 1: mode=none (no logs)
PHYLAXOR_LOGS_MODE=none docker-compose up -d
# Send alert, verify enriched event in Redis

# Test 2: mode=podlogs + RBAC 403 (OpenShift CRC)
# Deploy on CRC without pods/log RBAC
# Send alert, verify WARN in logs (graceful degradation)
```

## Development Guidelines

See **`.github/copilot-instructions.md`** for detailed guidelines:

- ✅ Test all logging modes before merging
- ✅ Update `docs/CONTRACT_ENV.md` before adding new env vars
- ✅ Handle RBAC 403 gracefully (warn + continue, never crash)
- ✅ Keep commits small and focused

## Deployment

See `phylaxor-gitops/` for Helm charts and deployment instructions.

### Deploy on Minikube

```bash
cd ../phylaxor-gitops
helm install phylaxor ./apps/phylaxor -f apps/phylaxor/values-minikube.yaml
```

### Deploy on OpenShift CRC

```bash
helm install phylaxor ./apps/phylaxor -f apps/phylaxor/values-openshift.yaml
```

## Next Steps

1. ✅ Configuration contract defined (env vars, defaults)
2. ⏳ Update enricher to respect `PHYLAXOR_LOGS_MODE`
3. ⏳ Add Loki provider and test on CRC
4. ⏳ Add E2E tests for all 3 modes

## References

- **`PHYLAXOR_CONTEXT.md`** (workspace root) — Original project brief
- **`phylaxor-gitops/`** — Helm charts, RBAC templates, ArgoCD apps
- **`docs/TEST_MATRIX.md`** — Acceptance criteria for all modes

---

**Last Updated**: December 2025  
**Contact**: SlavikBlxt4 (GitHub)
