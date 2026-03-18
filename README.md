# Phylaxor — Application Code

This repository contains the application services for Phylaxor.

Phylaxor is an incident-response assistant for Kubernetes/OpenShift:
- ingest receives Alertmanager payloads
- enricher adds cluster context and optional logs
- decision combines history, KB, and AI analysis
- notifier sends the result to Telegram
- feedback services capture operator feedback

For Helm charts and cluster deployment, see `../phylaxor-gitops`.

## Start Here

If you are new to the project, read these files in order:

1. `docs/README.md`
2. `docs/PROJECT_CONTEXT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/CONTRACT_ENV.md`
5. `docs/SECURITY_MODEL.md`

That path gives enough context to understand the system before diving into service code.

## Current State

What is already implemented in this repo:
- ingest -> enricher -> decision -> notifier pipeline
- feedback gateway and feedback dashboard
- logging modes with provider pattern in the enricher
- Brain Gateway integration for AI-generated recommendations
- decision ranking across history, KB, and AI/fallback paths

What is still incomplete or future-facing:
- Loki provider implementation
- end-to-end hardening of the AI path in cluster deployments
- operational cleanup and documentation consolidation

## Repository Structure

```text
phylaxor-project/
  docs/                       Core technical documentation
  infra/postgres/init.sql     Database schema bootstrap
  services/
    ingest/                   Alert ingestion
    enricher/                 Context enrichment and logs provider
    decision/                 Decision selection and Brain Gateway client
    brain_gateway/            OpenAI-facing structured response service
    notifier/                 Telegram sender
    feedback_gateway/         Telegram callback handler
    feedback/                 Dashboard and feedback API
  docker-compose.yml          Local development stack
```

## Local Development

```bash
cd phylaxor-project
docker-compose up -d
docker-compose logs -f enricher
```

Send a test alert:

```bash
curl -X POST http://localhost:8080/alert \
  -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"TestAlert","severity":"warning"},"annotations":{"summary":"Test alert"}}]}'
```

Stop everything:

```bash
docker-compose down
```

## Documentation Rules

When behavior changes:
- update `docs/PROJECT_CONTEXT.md` if project state changed
- update `docs/CONTRACT_ENV.md` before adding new env vars
- update `docs/ARCHITECTURE.md` if the service flow changed
- keep GitOps docs aligned when deployment behavior changes

## Related Repositories

- `phylaxor-gitops/`: Helm charts, RBAC, deployment values
