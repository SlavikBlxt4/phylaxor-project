import os
from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Phylaxor Brain Gateway"
    
    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    max_output_tokens: int = 4096

    # Debug
    brain_debug_raw: bool = Field(False, env="PHYLAXOR_BRAIN_DEBUG_RAW")
    brain_debug_mock: bool = Field(False, env="PHYLAXOR_BRAIN_DEBUG_MOCK")

    # Contracts
    contracts_dir: str = "/app/contracts"
    
    class Config:
        env_file = ".env"

settings = Settings()
