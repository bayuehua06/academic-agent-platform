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

    # AUT Library 登录（本机；勿提交真实密码）
    aut_username: str = ""
    aut_password: str = ""
    literature_test_query: str = "food delivery transformation"
    # 检索库入口（AUT 代理；全局注册表）
    literature_db_ieee_url: str = "https://library.aut.ac.nz/databases/ieee-xplore"
    literature_db_acm_url: str = "https://library.aut.ac.nz/databases/acm-digital-library"
    # 新建项目默认启用的库 id，逗号分隔：ieee,acm
    literature_default_databases: str = "ieee"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    # Writer 长文专用；空则回退 openai_model
    openai_writer_model: str = "gpt-4o"

    chrome_user_data_dir: str = ""
    chrome_profile_directory: str = "Default"
    # 推荐：连接已开启远程调试的当前 Chrome（避免 Profile 被占用）
    chrome_cdp_url: str = "http://127.0.0.1:9222"
    # NotebookLM 抓取默认有头模式；仅 persistent 模式有效
    notebooklm_headless: bool = False

    upload_dir: str = "./uploads"
    export_dir: str = "./exports"
    apa_csl_path: str = "./resources/apa.csl"
    # pandoc --reference-doc；缺失时由 apa_docx.build_apa_reference_docx 生成
    apa_reference_docx: str = "./resources/apa_reference.docx"


@lru_cache
def get_settings() -> Settings:
    """获取缓存的配置单例。"""
    return Settings()
