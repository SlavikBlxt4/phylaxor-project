import json
import os
from typing import Dict, Any
import jsonschema
from config import settings

class SchemaValidator:
    def __init__(self):
        self.contracts_dir = settings.contracts_dir
        self.request_schema = self._load_schema("ai_request.schema.json")
        self.response_schema = self._load_schema("ai_response.schema.json")

    def _load_schema(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.contracts_dir, filename)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Schema file not found: {path}")
        with open(path, 'r') as f:
            return json.load(f)

    def validate_request(self, payload: Dict[str, Any]):
        try:
            jsonschema.validate(instance=payload, schema=self.request_schema)
        except jsonschema.ValidationError as e:
            raise ValueError(f"Invalid AIRequest: {e.message}")

    def validate_response(self, payload: Dict[str, Any]):
        try:
            jsonschema.validate(instance=payload, schema=self.response_schema)
        except jsonschema.ValidationError as e:
            # We raise a different error for upstream (LLM) failures
            raise RuntimeError(f"Invalid AIResponse from LLM: {e.message}")

validator = SchemaValidator()
