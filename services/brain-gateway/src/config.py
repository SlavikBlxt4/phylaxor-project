import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "Phylaxor Brain Gateway"
    
    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 30.0
    max_output_tokens: int = 4096

    # Contracts
    contracts_dir: str = "/app/contracts"
    
    class Config:
        env_file = ".env"

settings = Settings()
