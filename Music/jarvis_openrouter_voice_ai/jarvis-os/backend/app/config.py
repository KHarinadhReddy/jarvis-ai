from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "J.A.R.V.I.S. Backend"
    version: str = "0.1.0"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "deepseek/deepseek-v4.1-flash"

    device_token: str = "jarvis-dev-token"
    allowed_origins: str = ""

    tts_voice_en: str = "en-IN-NeerjaNeural"
    tts_voice_te: str = "te-IN-ShrutiNeural"
    tts_rate_limit_per_minute: int = 30

    allow_mock: bool = False

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def provider_name(self) -> str:
        if self.deepseek_api_key:
            return "deepseek"
        if self.openrouter_api_key:
            return "openrouter"
        return "unconfigured"

    @property
    def provider_model(self) -> str:
        if self.deepseek_api_key:
            return self.deepseek_model
        if self.openrouter_api_key:
            return self.openrouter_model
        return ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
