# Copilot Instructions — Phylaxor Project

This file contains instructions for GitHub Copilot and other AI agents working on the Phylaxor project.

## Critical Context Documents

**Read these in order before suggesting changes to any code or configuration:**

1. **`ARCHITECTURE.md`** — High-level component flow and data pipeline
2. **`docs/PROJECT_CONTEXT.md`** — Global project goals, environments, current state
3. **`docs/CONTRACT_ENV.md`** — Environment variable specification (logging modes, feature flags)
4. **`docs/SECURITY_MODEL.md`** — RBAC requirements, security boundaries, "do not do" list
5. **`docs/LOGGING_MODES.md`** — Deep dive into logging modes (none/loki/podlogs)

These documents are the **single source of truth**. They override any assumptions or history you may have.

---

## Non-Negotiables (MUST follow)

### 1. No Kubernetes Secrets by Default
- **Rule**: Never add code that reads Kubernetes Secrets
- **Exception**: Only if explicitly approved via GitHub issue + security review
- **Action**: If a feature requires secret access, propose it in docs/SECURITY_MODEL.md first (don't code it)

### 2. Logging Must Respect Modes
- **Rule**: All log-reading code must check `PHYLAXOR_LOGS_MODE` environment variable
- **Behavior**:
  - If `PHYLAXOR_LOGS_MODE=none`: Skip log fetching entirely (do not attempt API call)
  - If `PHYLAXOR_LOGS_MODE=loki`: Use Loki client (not direct pod/log API)
  - If `PHYLAXOR_LOGS_MODE=podlogs`: Use Kubernetes API `pods/log` directly
- **Example check** (Python):
  ```python
  logs_mode = os.getenv("PHYLAXOR_LOGS_MODE", "none")
  if logs_mode == "none":
      logs_content = ""
  elif logs_mode == "loki":
      logs_content = fetch_from_loki(pod, namespace)
  elif logs_mode == "podlogs":
      logs_content = fetch_from_kubernetes_api(pod, namespace)
  ```

### 3. Graceful Degradation on RBAC Failures
- **Rule**: RBAC 403 errors (pods/log denied, etc.) must NOT break the pipeline
- **Behavior**:
  - Log a **WARN** message (not ERROR)
  - Continue processing without logs
  - Push enriched event to Redis (even without log content)
- **Example** (Python):
  ```python
  try:
      logs = fetch_logs(pod, namespace)
  except kubernetes.client.rest.ApiException as e:
      if e.status == 403:
          logger.warning(f"pods/log denied for pod {pod} in namespace {namespace}")
          logs = ""  # Continue without logs
      else:
          raise  # Re-raise other errors (network, auth, etc.)
  ```

### 4. Notifier Must Have NO Kubernetes Permissions
- **Rule**: Notifier component cannot access Kubernetes API
- **What this means**:
  - Notifier can only connect to: Telegram API, Postgres, Redis (internal)
  - Notifier cannot read pods, events, namespaces, secrets, etc.
  - Notifier cannot read logs
- **Why**: If notifier is compromised, attacker cannot access cluster
- **Helm verification**: Verify notifier's ServiceAccount has no RBAC rules

### 5. Degrade Gracefully, Never Crash on RBAC
- **Rule**: Any RBAC 403 error must be handled as a warning, not an exception
- **Example**: If enricher cannot read `pods/log`, it continues with available context
- **Anti-pattern** (❌ WRONG):
  ```python
  logs = kubernetes_client.get_logs(pod)  # Crashes on 403
  enriched_event = {**base_event, "logs": logs}
  ```
- **Pattern** (✅ RIGHT):
  ```python
  try:
      logs = fetch_logs_if_enabled(pod)
  except ApiException as e:
      if e.status == 403:
          logger.warning(f"Log access denied: {e}")
          logs = ""
      else:
          raise
  enriched_event = {**base_event, "logs": logs}
  ```

### 6. No Outbound Internet for Cluster-Aware Components
- **Rule**: Enricher and decision components can only reach:
  - Kubernetes API (internal)
  - Redis (internal)
  - Postgres (internal)
  - Loki (internal or internal-accessible)
- **Not allowed**: External APIs (except if explicitly configured via env var + docs)
- **Why**: Limit blast radius; cluster context must not leak to Internet

---

## Coding Guidelines

### 1. Test All Logging Modes
When adding log-reading features:
- [ ] Test with `PHYLAXOR_LOGS_MODE=none` (no logs attempted)
- [ ] Test with `PHYLAXOR_LOGS_MODE=podlogs` + RBAC granted (logs fetched)
- [ ] Test with `PHYLAXOR_LOGS_MODE=podlogs` + RBAC denied (graceful 403 handling)
- Reference: `docs/TEST_MATRIX.md`

### 2. Small Commits, Clear Messages
- Commit one feature or fix per commit
- Commit message format: `[component] short description`
- Example: `[enricher] add PHYLAXOR_LOGS_MODE check`, `[helm] make pods/log conditional`

### 3. Update Docs First, Then Code
- Before implementing: Update `docs/CONTRACT_ENV.md` with new env var or behavior
- Before merging: Ensure ARCHITECTURE.md and TEST_MATRIX.md reflect changes
- Rationale: Docs drive decisions; code follows

### 4. Prefer Provider Pattern for Log Backends
If adding a new logging backend (e.g., Datadog, Splunk):
```python
# Define interface
class LogProvider:
    def fetch_logs(self, pod: str, namespace: str) -> str: pass

# Implementations
class NoLogProvider(LogProvider): ...
class LokiProvider(LogProvider): ...
class PodLogsProvider(LogProvider): ...

# Factory
def get_log_provider(mode: str) -> LogProvider:
    if mode == "none":
        return NoLogProvider()
    elif mode == "loki":
        return LokiProvider(...)
    elif mode == "podlogs":
        return PodLogsProvider()
```

### 5. Minimize RBAC Surface
When touching Helm templates (phylaxor-gitops):
- Don't add permissions unless documented in `docs/RBAC_MODEL.md`
- Use conditional RBAC (grant `pods/log` only if mode=podlogs)
- See `phylaxor-gitops/docs/VALUES_EXAMPLES.md` for examples

### 6. Avoid Over-Permissioning
- **Anti-pattern**: Grant `*` or `admin` to a component
- **Pattern**: List exact resources and verbs needed
- **Example** (✅ correct):
  ```yaml
  rules:
    - apiGroups: [""]
      resources: ["pods"]
      verbs: ["get", "list"]
    - apiGroups: [""]
      resources: ["pods/log"]
      verbs: ["get"]
  ```

---

## Don't Do (Anti-Patterns)

### ❌ Don't Read Kubernetes Secrets Without Explicit Approval
```python
# WRONG: Never add this without security review
secrets = kubernetes_client.get_secret("default", "my-secret")
```

### ❌ Don't Ignore RBAC 403 Errors
```python
# WRONG: Will crash on 403
try:
    logs = fetch_logs(pod)
except:
    pass  # Silent failure, confusing behavior
```

### ❌ Don't Grant Broad Permissions
```yaml
# WRONG: Too permissive
rules:
  - apiGroups: ["*"]
    resources: ["*"]
    verbs: ["*"]
```

### ❌ Don't Add External API Access to Enricher/Decision
```python
# WRONG: Enricher calling random external API
response = requests.get("https://example.com/api/data")
```

### ❌ Don't Hardcode Logging Behavior
```python
# WRONG: No configuration choice
logs = kubernetes_client.get_logs(pod)  # Always fetches, no mode check
```

### ❌ Don't Make Notifier Have Kube Permissions
```yaml
# WRONG: Notifier should have zero kube RBAC
subjects:
  - name: phylaxor-notifier
    role: pods-reader  # This breaks the security model
```

### ❌ Don't Implement CRDs or Operators Yet
- Stay with Deployments + env vars (MVP phase)
- CRDs can be added later when contract is stable

---

## When to Ask for Help

Before implementing changes, check with maintainers if:

1. **Adding a new environment variable** → Update `docs/CONTRACT_ENV.md` first
2. **Adding new RBAC permissions** → Ensure documented in `docs/SECURITY_MODEL.md`
3. **Changing enricher behavior** → Verify matches modes in `docs/LOGGING_MODES.md`
4. **Adding a new microservice** → Ensure it follows RBAC guidelines
5. **Removing or deprecating a feature** → Check `PHYLAXOR_CONTEXT.md` for context

---

## Related Documents

- **`ARCHITECTURE.md`** — Component architecture and data flow
- **`docs/PROJECT_CONTEXT.md`** — Global context (read first)
- **`docs/CONTRACT_ENV.md`** — Environment variable contract
- **`docs/SECURITY_MODEL.md`** — RBAC and security boundaries
- **`docs/LOGGING_MODES.md`** — Logging mode analysis
- **`docs/TEST_MATRIX.md`** — E2E test scenarios

---

## Quick Reference

| Issue | Check This | Action |
|-------|-----------|--------|
| "Does Phylaxor read Secrets?" | `docs/SECURITY_MODEL.md` | Don't add unless approved |
| "What logging modes exist?" | `docs/LOGGING_MODES.md` | Follow mode contract |
| "What permissions does X have?" | `docs/SECURITY_MODEL.md` + Helm | Grant minimum only |
| "How do I add a new env var?" | `docs/CONTRACT_ENV.md` | Document first, implement second |
| "What should notifier access?" | `docs/SECURITY_MODEL.md` | No kube/log permissions |
| "How do I handle RBAC 403?" | `docs/LOGGING_MODES.md` | Warn + continue, never crash |

