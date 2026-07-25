"""应用配置（Pydantic Settings）。"""

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，支持环境变量与 .env 文件覆盖。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Academic Agent Platform"
    app_env: str = "development"
    debug: bool = True
    api_prefix: str = "/api"

    secret_key: str = "change-me-to-a-long-random-secret-key"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"

    database_url: str = (
        "postgresql+asyncpg://academic:academic_secret@localhost:5432/academic_agent"
    )

    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:1980"])

    zotero_library_id: str = ""
    zotero_api_key: str = ""
    zotero_library_type: str = "user"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    chrome_user_data_dir: str = ""
    chrome_profile_directory: str = "Default"

    upload_dir: str = "./uploads"
    export_dir: str = "./exports"
    apa_csl_path: str = "./resources/apa.csl"


@lru_cache
def get_settings() -> Settings:
    """获取缓存的配置单例。"""
    return Settings()
