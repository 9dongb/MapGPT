from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql://mapgpt:mapgpt@localhost:5432/mapgpt"

    llm_provider: Literal["openai", "ollama"] = "openai"
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-6.1-sol"
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str | None = None
    # thinking 모델의 추론 강도 (예: none이면 끔). 비우면 모델 기본값을 쓴다.
    ollama_reasoning_effort: str | None = None

    seoul_open_api_key: SecretStr | None = None
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
