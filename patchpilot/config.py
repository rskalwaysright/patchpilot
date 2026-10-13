import os
from typing import Dict
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


class PricingModel(BaseModel):
    prompt_per_1k: float
    completion_per_1k: float


# Pricing per 1k tokens in USD for cost accounting
DEFAULT_PRICING: Dict[str, PricingModel] = {
    "mock": PricingModel(prompt_per_1k=0.0, completion_per_1k=0.0),
    "gpt-4o-mini": PricingModel(prompt_per_1k=0.00015, completion_per_1k=0.0006),
    "gpt-4o": PricingModel(prompt_per_1k=0.0025, completion_per_1k=0.010),
    "claude-3-5-sonnet-20241022": PricingModel(prompt_per_1k=0.003, completion_per_1k=0.015),
}


class Settings(BaseModel):
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "mock"))
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_base_url: str = Field(default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    openai_model: str = Field(default_factory=lambda: os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_api_key: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = Field(default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022"))
    
    default_token_budget: int = Field(default_factory=lambda: int(os.getenv("DEFAULT_TOKEN_BUDGET", "4000")))
    max_output_tokens: int = Field(default_factory=lambda: int(os.getenv("MAX_OUTPUT_TOKENS", "1024")))
    sandbox_timeout_seconds: int = Field(default_factory=lambda: int(os.getenv("SANDBOX_TIMEOUT_SECONDS", "15")))
    enable_safe_subprocess_fallback: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_SAFE_SUBPROCESS_FALLBACK", "true").lower() == "true"
    )
    cache_dir: str = Field(default_factory=lambda: os.path.join(os.path.expanduser("~"), ".patchpilot_cache"))


settings = Settings()
