from __future__ import annotations

from fastapi import Depends

from .config import Settings, get_settings
from .providers import AIProvider, build_provider


def get_provider() -> AIProvider:
    return build_provider(get_settings())


def get_app_settings() -> Settings:
    return get_settings()


ProviderDep = Depends(get_provider)
SettingsDep = Depends(get_app_settings)
