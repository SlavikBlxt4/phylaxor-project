import json
import time
import logging
from typing import Dict, Any, Optional
from openai import AsyncOpenAI, APIError
from config import settings
from schemas import validator

logger = logging.getLogger("brain_gateway")

# Pricing constants for gpt-4o-mini (approximate)
# Input: $0.15 / 1M tokens
# Output: $0.60 / 1M tokens
COST_PER_1M_INPUT_TOKENS = 0.15
COST_PER_1M_OUTPUT_TOKENS = 0.60

class InvalidAIRequest(Exception):
    pass

class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        
        # System prompt enforcing strict JSON and read-only behavior
        self.system_prompt = (
            "You are a Senior Site Reliability Engineer (SRE) assistant named Phylaxor. "
            "Your role is to analyze Kubernetes alerts and context to provide structured diagnosis and recommendations.\n"
            "CRITICAL RULES:\n"
            "1. You are strictly READ-ONLY. Do not execute any actions.\n"
            "2. Never recommend destructive commands (delete, mkfs, etc.) without explicit warning and strict validation.\n"
            "3. Output MUST be valid JSON conforming to the AIResponse schema.\n"
            "4. Do not include markdown formatting (```json) in your response, just the raw JSON object.\n"
            "5. Analyze logs carefully for root cause.\n"
            "6. Use the provided context constraints.\n"
            "7. Return one JSON object with these keys: summary, triage, hypotheses, recommendedActions, checks, fixes, missingInfo, safety, suggestedToolCalls.\n"
            "8. triage.confidence MUST be a number between 0 and 1.\n"
            "9. checks items MUST be objects with: title, commands[], reason.\n"
            "10. fixes items MUST be objects with: title, steps[], risk(low|medium|high), requiresWrite(boolean).\n"
        )

    def _to_confidence(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return max(0.0, min(1.0, float(value)))
        if isinstance(value, str):
            val = value.strip().lower()
            if val == "high":
                return 0.9
            if val == "medium":
                return 0.6
            if val == "low":
                return 0.3
            try:
                num = float(val)
                return max(0.0, min(1.0, num))
            except Exception:
                return 0.0
        return 0.0

    def _normalize_hypotheses(self, raw: Any) -> list:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict):
                title = (item.get("title") or item.get("description") or "").strip()
                confidence = self._to_confidence(item.get("confidence"))
                evidence = item.get("evidence")
                if isinstance(evidence, str):
                    evidence = [evidence]
                if not isinstance(evidence, list):
                    evidence = []
                evidence = [str(e).strip() for e in evidence if str(e).strip()]
                impact = (item.get("impact") or "").strip()
                if title or evidence or impact:
                    out.append({
                        "title": title or "Unspecified hypothesis",
                        "confidence": confidence,
                        "evidence": evidence,
                        "impact": impact or "Impact not specified",
                    })
            elif isinstance(item, str) and item.strip():
                out.append({
                    "title": item.strip(),
                    "confidence": 0.0,
                    "evidence": [],
                    "impact": "Impact not specified",
                })
        return out

    def _normalize_checks(self, raw: Any) -> list:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict):
                title = (item.get("title") or "").strip()
                commands = item.get("commands")
                if isinstance(commands, str):
                    commands = [commands]
                if not isinstance(commands, list):
                    commands = []
                commands = [str(c).strip() for c in commands if str(c).strip()]
                reason = (item.get("reason") or "").strip()
                if title or commands or reason:
                    out.append({
                        "title": title or "Diagnostic check",
                        "commands": commands,
                        "reason": reason or "Generated from model output normalization",
                    })
            elif isinstance(item, str) and item.strip():
                out.append({
                    "title": "Diagnostic check",
                    "commands": [item.strip()],
                    "reason": "Generated from legacy string check format",
                })
        return out

    def _normalize_fixes(self, raw: Any) -> list:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict):
                title = (item.get("title") or item.get("action") or "").strip()
                steps = item.get("steps")
                if isinstance(steps, str):
                    steps = [steps]
                if not isinstance(steps, list):
                    steps = []
                steps = [str(s).strip() for s in steps if str(s).strip()]
                risk = (item.get("risk") or "").strip().lower()
                if risk not in ("low", "medium", "high"):
                    risk = "medium"
                requires_write = bool(item.get("requiresWrite", False))
                if title or steps:
                    out.append({
                        "title": title or "Potential fix",
                        "steps": steps,
                        "risk": risk,
                        "requiresWrite": requires_write,
                    })
            elif isinstance(item, str) and item.strip():
                out.append({
                    "title": "Potential fix",
                    "steps": [item.strip()],
                    "risk": "medium",
                    "requiresWrite": False,
                })
        return out

    def _normalize_ai_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        # Accept common wrapped formats from LLM outputs.
        if isinstance(payload.get("response"), dict):
            payload = payload["response"]
        elif isinstance(payload.get("aiResponse"), dict):
            payload = payload["aiResponse"]
        elif isinstance(payload.get("result"), dict):
            payload = payload["result"]
        elif isinstance(payload.get("output"), dict):
            payload = payload["output"]

        summary = payload.get("summary") or payload.get("diagnosisSummary") or ""
        if not isinstance(summary, str):
            summary = str(summary)

        triage = payload.get("triage") if isinstance(payload.get("triage"), dict) else {}
        severity = triage.get("severity") or "unknown"
        if severity not in ("critical", "warning", "info", "unknown"):
            severity = "unknown"
        category = triage.get("category") or "unknown"
        if not isinstance(category, str):
            category = str(category)
        confidence = self._to_confidence(triage.get("confidence"))

        missing_info = payload.get("missingInfo", payload.get("missing_info", []))
        if isinstance(missing_info, str):
            missing_info = [missing_info]
        if not isinstance(missing_info, list):
            missing_info = []
        missing_info = [str(i).strip() for i in missing_info if str(i).strip()]

        recommended_actions = payload.get("recommendedActions", payload.get("recommended_actions", []))
        if isinstance(recommended_actions, str):
            recommended_actions = [recommended_actions]
        if not isinstance(recommended_actions, list):
            recommended_actions = []

        safety = payload.get("safety")
        if not isinstance(safety, dict):
            safety_notes = payload.get("safety_notes")
            notes = [safety_notes] if isinstance(safety_notes, str) else []
            safety = {"notes": notes}
        else:
            notes = safety.get("notes")
            if isinstance(notes, str):
                safety["notes"] = [notes]
            elif not isinstance(notes, list):
                safety["notes"] = []
            else:
                safety["notes"] = [str(n).strip() for n in notes if str(n).strip()]

        tool_calls = payload.get("suggestedToolCalls", payload.get("suggested_tool_calls", []))
        if not isinstance(tool_calls, list):
            tool_calls = []

        normalized = {
            "summary": summary.strip() or "No summary provided by model",
            "triage": {
                "severity": severity,
                "confidence": confidence,
                "category": category.strip() or "unknown",
            },
            "hypotheses": self._normalize_hypotheses(payload.get("hypotheses", [])),
            "recommendedActions": recommended_actions,
            "checks": self._normalize_checks(payload.get("checks", [])),
            "fixes": self._normalize_fixes(payload.get("fixes", [])),
            "missingInfo": missing_info,
            "safety": safety,
            "suggestedToolCalls": tool_calls,
        }
        return normalized

    async def generate_response(
        self, 
        ai_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Calls OpenAI API with the AIRequest and returns the raw AIResponse dict.
        Also injects usage metadata.
        """
        start_time = time.time()
        request_id = ai_request.get("meta", {}).get("requestId", "unknown")

        # Pre-validate before calling OpenAI (defense-in-depth)
        try:
            validator.validate_request(ai_request)
        except ValueError as e:
            logger.warning(f"AIRequest pre-validation failed (request_id={request_id}): {e}")
            raise InvalidAIRequest(str(e))
        
        if settings.brain_debug_mock:
            logger.info(f"Debug mock enabled (request_id={request_id}), skipping OpenAI call")
            latency_ms = int((time.time() - start_time) * 1000)
            ai_response = self._mock_response(ai_request)
            ai_response["schemaVersion"] = "1.0"
            ai_response["requestId"] = request_id
            ai_response["provider"] = "debug"
            ai_response["model"] = "debug-mock"
            ai_response["usage"] = {
                "inputTokens": 0,
                "outputTokens": 0,
                "estimatedCostUsd": 0,
                "latencyMs": latency_ms
            }
            return ai_response

        # 1. Prepare messages
        user_content = json.dumps(ai_request)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content}
        ]

        try:
            # 2. Call OpenAI
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                max_tokens=settings.max_output_tokens,
                temperature=0.2, # Low temperature for consistent technical analysis
                timeout=settings.openai_timeout_seconds,
                response_format={"type": "json_object"}
            )
            
            # 3. Calculate metrics
            latency_ms = int((time.time() - start_time) * 1000)
            usage = response.usage
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens
            
            cost_est = (
                (input_tokens / 1_000_000 * COST_PER_1M_INPUT_TOKENS) +
                (output_tokens / 1_000_000 * COST_PER_1M_OUTPUT_TOKENS)
            )

            # 4. Parse content
            content_str = response.choices[0].message.content
            if not content_str:
                raise ValueError("Empty response from OpenAI")

            if settings.brain_debug_raw:
                logger.info(f"OpenAI raw response (request_id={request_id}): {content_str}")

            try:
                ai_response = json.loads(content_str)
            except json.JSONDecodeError:
                raise ValueError("OpenAI returned invalid JSON")

            if not isinstance(ai_response, dict):
                raise ValueError("OpenAI returned JSON that is not an object")

            ai_response = self._normalize_ai_response(ai_response)

            # 5. Inject metadata (server-populated fields)
            # Schema version is assumed 1.0 based on current implementation
            ai_response["schemaVersion"] = "1.0"
            ai_response["requestId"] = ai_request.get("meta", {}).get("requestId", "unknown")
            ai_response["provider"] = "openai"
            ai_response["model"] = self.model
            
            ai_response["usage"] = {
                "inputTokens": input_tokens,
                "outputTokens": output_tokens,
                "estimatedCostUsd": round(cost_est, 6),
                "latencyMs": latency_ms
            }

            return ai_response

        except APIError as e:
            logger.error(f"OpenAI API Error: {e}")
            raise RuntimeError(f"OpenAI API Error: {str(e)}")
        except Exception as e:
            logger.error(f"Unexpected error in AI client: {e}")
            raise

    def _mock_response(self, ai_request: Dict[str, Any]) -> Dict[str, Any]:
        alert = ai_request.get("alert", {})
        alertname = alert.get("alertname", "UnknownAlert")
        fingerprint = alert.get("fingerprint", "unknown")
        namespace = (alert.get("labels") or {}).get("namespace")
        ns_label = namespace if namespace else "unknown-namespace"

        return {
            "summary": f"[DEBUG MOCK] {alertname} ({fingerprint}) in {ns_label}.",
            "triage": {
                "severity": "info",
                "confidence": 0.01,
                "category": "debug"
            },
            "hypotheses": [],
            "recommendedActions": [
                "[DEBUG MOCK] This is a fake response. Disable PHYLAXOR_BRAIN_DEBUG_MOCK to call OpenAI."
            ],
            "checks": [],
            "fixes": [],
            "missingInfo": [],
            "safety": {
                "notes": [
                    "Debug mode: no real AI call was made."
                ]
            },
            "suggestedToolCalls": []
        }

ai_client = OpenAIClient()
