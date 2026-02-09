# Phylaxor AI Agent Contract

This directory contains the formal integration contract between the Phylaxor Decision Engine (Backend) and the AI Agent (LLM).

**Version:** 1.0.0-draft
**Status:** Stable / For Implementation

## Interaction Model

The interaction is **Single-Shot Request/Response**:
1. **Phylaxor** aggregates an Alert, Context (Clusters, Resources), and Constraints into an `AIRequest`.
2. **AI Agent** analyzes the data and returns a structured `AIResponse`.

## Schemas

- **[ai_request.schema.json](./ai_request.schema.json)**:
  - Defines the input payload sent to the LLM.
  - Includes strict constraints: `readOnly: true`, `noDestructiveActions: true`.
  - Enforces `context.alertContext.logs` presence (string or null).

- **[ai_response.schema.json](./ai_response.schema.json)**:
  - Defines the structured output expected from the LLM.
  - Enforces `triage`, `hypotheses`, `checks` (read-only commands), and `fixes` (runbooks).
  - Includes `suggestedToolCalls` for future agentic capabilities (advisory only).

## Examples

The `examples/` directory contains valid JSON payloads demonstrating the contract:

- **[no_logs_simple.json](./examples/no_logs_simple.json)**:
  - Scenario: Node NotReady alert.
  - Highlights: Handling `null` logs, Infrastructure triage.

- **[with_logs_repetitive.json](./examples/with_logs_repetitive.json)**:
  - Scenario: Pod CrashLoopBackOff with Java OOM logs.
  - Highlights: Log analysis evidence, Application triage, Suggested Tool Calls.

## Validation Rules

1. All timestamps must be ISO 8601 `date-time`.
2. `AIResponse` MUST be valid JSON. No markdown fencing (```json) outside the parsed content.
3. `confidence` scores must be float `0.0` - `1.0`.
4. `checks` MUST contain only read-only `kubectl` commands (get, describe, logs, top).
5. `fixes` MUST set `requiresWrite: false` for this version.

## Usage

When implementing the client:
1. Validate generated `AIRequest` against `ai_request.schema.json`.
2. Parse LLM output.
3. Validate parsed output against `ai_response.schema.json`.
4. If validation fails, fallback to a "Raw Output" capture mode or retry.
