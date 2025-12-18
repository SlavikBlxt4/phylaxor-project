# Phylaxor Architecture

## Overview

Phylaxor is a microservice-based incident-response assistant for Kubernetes/OpenShift that consumes alerts, enriches them with cluster context, applies knowledge-base rules, and notifies SRE teams. The goal is to reduce MTTR by providing actionable, context-aware troubleshooting steps.

## Core Alert Processing Flow

```
┌─────────────────┐
│  Alertmanager   │
│   Webhook       │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│  ingest                                                     │
│  • Receives alert payload (HTTP POST)                       │
│  • Normalizes to minimal event format                       │
│  • Pushes to Redis                                          │
└────────┬────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│   Redis List         │
│  phylaxor_raw        │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  enricher                                                   │
│  • Reads raw alert from Redis                               │
│  • Attaches cluster context (nodes, storage, events)        │
│  • Fetches logs (if enabled: none/loki/podlogs)            │
│  • Pushes enriched event to Redis                           │
│  • Degrades gracefully on RBAC failures                     │
└────────┬─────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│   Redis List         │
│  phylaxor_enriched   │
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│  decision                                                   │
│  • Queries historical decisions (Postgres)                  │
│  • Matches against KB rules (Postgres)                      │
│  • Produces recommendation with confidence + reasoning      │
│  • Pushes decision to Redis                                 │
└────────┬─────────────────────────────────────────────────────┘
         │
         ├──────────────────────────────┬────────────────────────┐
         ▼                              ▼                        ▼
    ┌──────────┐              ┌─────────────────┐      ┌──────────────────┐
    │ notifier │              │ Postgres        │      │ feedback-gateway │
    │ (Telegram)              │ (decisions)     │      │ (Telegram client)│
    └──────────┘              └─────────────────┘      └──────────────────┘
         │                                                      │
         └──────────────────────────────┬─────────────────────┘
                                        ▼
                             ┌─────────────────────────┐
                             │ Postgres                │
                             │ • decisions             │
                             │ • feedback (votes)      │
                             │ • kb_items/matchers     │
                             │ • alerts                │
                             └─────────────────────────┘
```

## Components

### ingest
- **Purpose**: HTTP endpoint to receive alerts (typically from Alertmanager)
- **Input**: Alert payload (JSON)
- **Output**: Normalized event pushed to `phylaxor_raw` Redis list
- **Permissions**: None (HTTP-only, no kube/log access needed)

### enricher
- **Purpose**: Enrich raw alerts with cluster context
- **Input**: Raw event from Redis
- **Output**: Enriched event to `phylaxor_enriched` Redis list
- **Context added**:
  - Cluster metadata (version, nodes, storage)
  - Pod/node/resource status
  - Recent cluster events
  - Pod logs (when enabled via `PHYLAXOR_LOGS_MODE`)
- **Permissions**: Observer + conditional log read access (see docs/SECURITY_MODEL.md)
- **Resilience**: Degrades gracefully on RBAC 403 errors; pipeline does not fail

### decision
- **Purpose**: Generate recommendations based on history and KB
- **Input**: Enriched event from Redis
- **Process**:
  1. Look up historical decisions (via alert fingerprint in Postgres)
  2. Match KB rules (matchers + metadata) in Postgres
  3. Fallback recommendation if no KB match
- **Output**: Decision record (KB path / history / fallback) to Postgres + Redis
- **Permissions**: Read-only to Postgres decision/KB tables

### notifier
- **Purpose**: Send notification to on-call team (Telegram)
- **Input**: Decision from Redis
- **Output**: Telegram message with interactive buttons
- **Important**: Must **NOT** have Kubernetes or logging permissions
- **Permissions**: None (external API call only)

### feedback-gateway
- **Purpose**: Handle Telegram callback responses and record feedback
- **Input**: Telegram callback webhooks
- **Output**: Vote record to Postgres `feedback` table
- **Permissions**: Write to Postgres feedback table only

## Key Architectural Decisions

### 1. Redis as Event Queue
- Redis lists (`phylaxor_raw`, `phylaxor_enriched`) decouple components
- Allows independent scaling and restart without event loss
- Simple, reliable for MVP stage

### 2. Configurable Logging Modes
See `docs/CONTRACT_ENV.md` and `docs/LOGGING_MODES.md` for details.

- **`none`**: No log access (safest, no risk of leaking sensitive data)
- **`loki`**: Centralized logging backend (recommended for enterprise)
- **`podlogs`**: Direct Kubernetes API log read (requires explicit enable + RBAC grant)

### 3. Graceful Degradation
RBAC 403 errors (e.g., pod/logs not permitted) trigger a warning log but do **NOT** break the pipeline. Enricher continues with available context.

### 4. Separation of Duties
- Components reading cluster data have no outbound Internet access
- Notifier (Telegram/Internet) has no Kubernetes permissions
- Reduces blast radius if a component is compromised

### 5. Postgres as Source of Truth
- KB rules, historical decisions, and feedback stored in Postgres
- Redis is ephemeral (events only)
- Enables decision history analysis and rule refinement

## Database Schema (Simplified)

| Table | Purpose |
|-------|---------|
| `kb_items` | Knowledge base entries: checks, fixes, severity, tags |
| `kb_matchers` | Rules linking kb_items to alert patterns (alertname, namespace, labels, regex) |
| `alerts` | Alert instances: fingerprint, alertname, labels, timestamps |
| `decisions` | Recommendations: path (history/kb/fallback), kb_id, confidence, reason |
| `feedback` | User votes on decisions: decision_id FK, vote (bool), notes |

## Related Documentation

- **`docs/PROJECT_CONTEXT.md`** — Global project context (canonical reference)
- **`docs/CONTRACT_ENV.md`** — Environment variable contract (logging modes, feature flags)
- **`docs/SECURITY_MODEL.md`** — Security boundaries and RBAC principles
- **`docs/LOGGING_MODES.md`** — Deep dive into logging modes (risks, use cases, enterprise recommendations)
- **`docs/TEST_MATRIX.md`** — E2E test scenarios for each logging mode
