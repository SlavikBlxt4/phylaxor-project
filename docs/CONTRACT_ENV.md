# Configuration Contract — Phylaxor

This document defines the **environment variable contract** for Phylaxor microservices. This is the single source of truth for configuration across all deployments (Minikube, OpenShift CRC, production).

## Environment Variables (MVP)

### Logging Configuration

#### `PHYLAXOR_LOGS_MODE`
- **Type**: String (enum)
- **Values**: `none` | `loki` | `podlogs`
- **Default**: `none`
- **Required**: No

Controls how enricher fetches pod logs for context:

- **`none`**: Do NOT fetch logs. Use only cluster events and resource status.
  - Safest mode; zero RBAC complexity
  - No risk of leaking secrets through log content
  - Recommended for non-critical environments or when logs are unavailable

- **`loki`**: Fetch logs from centralized logging backend (OpenShift Logging / LokiStack).
  - **Status**: Placeholder (implementation pending)
  - **When available**: Recommended for enterprise environments
  - Requires Loki to be deployed and accessible from enricher
  - Requires Loki endpoint, tenant, auth credentials (see Loki settings below)

- **`podlogs`**: Fetch logs via Kubernetes API `pods/log`.
  - **Default**: Disabled (must be explicitly enabled)
  - **Risk**: High — pod logs may contain sensitive data (secrets, API keys, credentials)
  - **RBAC requirement**: Explicit grant of `pods/log` permission via ClusterRole
  - **Failure mode**: If RBAC 403 occurs, enricher logs warning but continues (graceful degradation)
  - **When to use**: Manual fallback if Loki is unavailable; only in non-prod or tightly controlled environments

#### `PHYLAXOR_EVENTS_ENABLED`
- **Type**: Boolean
- **Values**: `true` | `false`
- **Default**: `true`
- **Required**: No

Enable/disable fetching cluster events (non-log context):

- **`true`**: Enricher fetches recent cluster events (pod/node/deployment changes)
  - Low risk; events do not expose secrets
  - Recommended enabled for better context

- **`false`**: Skip event enrichment
  - Use only log context (if enabled) and resource status

#### `PHYLAXOR_LOGS_MAX_LINES`
- **Type**: Integer
- **Default**: `500`
- **Required**: No
- **Unit**: Lines

Maximum number of log lines to fetch per pod.

- **Rationale**: Prevent excessive memory/bandwidth when fetching logs
- **Recommended**: `100`–`500` depending on log verbosity

#### `PHYLAXOR_LOGS_MAX_BYTES`
- **Type**: Integer
- **Default**: `100000` (100 KB)
- **Required**: No
- **Unit**: Bytes

Maximum byte size of log context to include in enriched event.

- **Rationale**: Prevent Redis/Postgres payload bloat
- **Recommended**: `50000`–`200000` depending on storage/network

#### `PHYLAXOR_LOGS_LOOKBACK`
- **Type**: Integer
- **Default**: `300`
- **Required**: No
- **Unit**: Seconds

How far back in time to fetch logs (e.g., 300 = last 5 minutes).

- **Rationale**: Relevant logs typically occur near incident onset
- **Recommended**: `300`–`600` (5–10 minutes)

### Loki Integration (Placeholder)

The following env vars are placeholders for future Loki provider implementation.

#### `PHYLAXOR_LOKI_ENABLED`
- **Type**: Boolean
- **Default**: `false`
- **Required**: No

Enable Loki backend (only if `PHYLAXOR_LOGS_MODE=loki`).

#### `PHYLAXOR_LOKI_ENDPOINT`
- **Type**: String (URL)
- **Example**: `https://loki.monitoring.svc.cluster.local:3100`
- **Required**: If `PHYLAXOR_LOGS_MODE=loki`

Loki query API endpoint.

#### `PHYLAXOR_LOKI_TENANT_ID`
- **Type**: String
- **Example**: `phylaxor`
- **Required**: If `PHYLAXOR_LOGS_MODE=loki`

Loki tenant ID (if multi-tenant Loki is configured).

#### `PHYLAXOR_LOKI_USERNAME` / `PHYLAXOR_LOKI_PASSWORD`
- **Type**: String
- **Required**: If Loki requires HTTP basic auth

Credentials for Loki endpoint. Typically stored as Kubernetes Secrets.

#### `PHYLAXOR_LOKI_BEARER_TOKEN`
- **Type**: String
- **Required**: If Loki requires bearer token auth

Alternative to basic auth for Loki.

### Brain Gateway (Decision → AI)

These variables control how the **decision** service calls the Brain Gateway (`POST /v1/brain/complete`).

#### `BRAIN_GATEWAY_URL`
- **Type**: String (URL)
- **Default**: `http://brain-gateway:8080`
- **Required**: No

Base URL for Brain Gateway. The decision service appends `/v1/brain/complete`.

#### `BRAIN_GATEWAY_TIMEOUT_SECONDS`
- **Type**: Float
- **Default**: `20`
- **Required**: No

HTTP timeout for Brain Gateway requests.

#### `BRAIN_GATEWAY_MAX_RETRIES`
- **Type**: Integer
- **Default**: `2`
- **Required**: No

Maximum retry attempts for transient failures (5xx/timeouts only).

#### `BRAIN_GATEWAY_RETRY_BACKOFF_MS`
- **Type**: Integer
- **Default**: `250`
- **Required**: No

Base backoff (in milliseconds) between retries.

#### `BRAIN_GATEWAY_MAX_OUTPUT_TOKENS`
- **Type**: Integer
- **Default**: `1024`
- **Required**: No

Max tokens requested in the AIResponse (passed via AIRequest `limits.maxOutputTokens`).

#### `PHYLAXOR_BRAIN_DEBUG_RAW`
- **Type**: Boolean
- **Default**: `false`
- **Required**: No

When `true`, Brain Gateway logs the raw OpenAI response text (useful for debugging schema validation errors).

#### `PHYLAXOR_BRAIN_DEBUG_MOCK`
- **Type**: Boolean
- **Default**: `false`
- **Required**: No

When `true`, Brain Gateway skips the OpenAI call and returns a deterministic mock response (for safe local/CI iteration).

## Expected Behavior by Mode

### Mode: `none`

```
enricher:
  1. Reads raw alert from Redis
  2. Fetches cluster events (if PHYLAXOR_EVENTS_ENABLED=true)
  3. Fetches pod/node/storage status
  4. Does NOT fetch logs
  5. Pushes enriched event to Redis
```

**RBAC required**: Observer (read pods, nodes, events)
**No RBAC issues**: pods/log not accessed

### Mode: `loki`

```
enricher:
  1. Reads raw alert from Redis
  2. Fetches cluster events (if PHYLAXOR_EVENTS_ENABLED=true)
  3. Fetches pod/node/storage status
  4. Queries Loki for logs (via PHYLAXOR_LOKI_ENDPOINT)
  5. Includes relevant log snippet in enriched event
  6. Pushes enriched event to Redis
```

**RBAC required**: Observer (no pod/log permission needed; logs come from Loki)
**Loki access required**: Endpoint, tenant ID, authentication credentials

### Mode: `podlogs` (Explicit Opt-In)

```
enricher:
  1. Reads raw alert from Redis
  2. Fetches cluster events (if PHYLAXOR_EVENTS_ENABLED=true)
  3. Fetches pod/node/storage status
  4. Attempts to fetch pod logs via Kubernetes API (pods/log)
  5a. If successful: includes log snippet in enriched event
  5b. If RBAC 403: Logs warning ("pods/log denied"), continues WITHOUT logs
  6. Pushes enriched event to Redis
```

**RBAC required**: Observer + explicit `pods/log` permission
**Failure mode**: Graceful (403 warnings, no pipeline break)
**Important**: This mode should be disabled by default and enabled only after explicit review

## Defaults (MVP)

| Variable | Default Value | Reason |
|----------|---------------|--------|
| `PHYLAXOR_LOGS_MODE` | `none` | Safest; zero log exposure risk |
| `PHYLAXOR_EVENTS_ENABLED` | `true` | Events are low-risk; valuable for context |
| `PHYLAXOR_LOGS_MAX_LINES` | `500` | Reasonable balance between coverage and size |
| `PHYLAXOR_LOGS_MAX_BYTES` | `100000` | ~100 KB per event; prevents bloat |
| `PHYLAXOR_LOGS_LOOKBACK` | `300` | Most relevant logs within 5 min of alert |
| `PHYLAXOR_LOKI_ENABLED` | `false` | Placeholder; not required for MVP |

## Examples

### Example 1: Minikube Dev (Safe, No Logs)
```bash
PHYLAXOR_LOGS_MODE=none
PHYLAXOR_EVENTS_ENABLED=true
```
→ Fast iteration, no RBAC complexity, no log exposure.

### Example 2: Minikube with Pod Logs (Testing)
```bash
PHYLAXOR_LOGS_MODE=podlogs
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOGS_MAX_LINES=200
PHYLAXOR_LOGS_LOOKBACK=600
```
→ Requires RBAC grant for `pods/log`; useful for testing graceful degradation.

### Example 3: OpenShift CRC (Enterprise Simulation, No Logs)
```bash
PHYLAXOR_LOGS_MODE=none
PHYLAXOR_EVENTS_ENABLED=true
```
→ Validates tight RBAC without log complexity.

### Example 4: OpenShift with Loki (Future Enterprise Path)
```bash
PHYLAXOR_LOGS_MODE=loki
PHYLAXOR_EVENTS_ENABLED=true
PHYLAXOR_LOKI_ENDPOINT=https://loki.logging.svc.cluster.local:3100
PHYLAXOR_LOKI_TENANT_ID=phylaxor
PHYLAXOR_LOKI_USERNAME=phylaxor-user
PHYLAXOR_LOKI_PASSWORD=<secret-from-k8s-secret>
```
→ Recommended enterprise path; centralized logging without pod/log RBAC burden.

## How to Extend

If adding new configuration:

1. Define it here with type, default, and rationale
2. Document expected behavior in `docs/SECURITY_MODEL.md` if security-relevant
3. Update example deployments in `phylaxor-gitops/docs/VALUES_EXAMPLES.md`
4. Add acceptance tests in `docs/TEST_MATRIX.md`

## Related Documents

- **`docs/PROJECT_CONTEXT.md`** — Global project context
- **`docs/SECURITY_MODEL.md`** — RBAC and security implications
- **`docs/LOGGING_MODES.md`** — Deep analysis of logging modes
- **`ARCHITECTURE.md`** — Component interaction (enricher behavior)
