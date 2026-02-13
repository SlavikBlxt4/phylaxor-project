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
        )

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
