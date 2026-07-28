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
    writer_evidence_keyword_top_n: int = 20
    writer_evidence_top_k: int = 3
    writer_evidence_best_score_min: int = 2
    writer_evidence_max_chunks_per_source: int = 3
    writer_evidence_max_chars_per_section: int = 12000
    writer_evidence_fallback_mode: str = "both"
    writer_evidence_enrich_max_sources: int = 8
    writer_evidence_http_timeout_seconds: float = 4.0
    writer_evidence_user_agent: str = "AcademicAgentPlatform/1.4 evidence-fetch"
    # CE4: PDF 全文（Zotero 附件 / Unpaywall OA）
    writer_evidence_enable_zotero_pdf: bool = True
    writer_evidence_enable_unpaywall: bool = True
    writer_evidence_pdf_max_sources: int = 6
    writer_evidence_pdf_max_pages: int = 20
    writer_evidence_pdf_max_chars: int = 16000
    # Unpaywall 要求有效邮箱；空则跳过 OA PDF
    writer_evidence_unpaywall_email: str = ""
    # True 时忽略 literatures.evidence_text 缓存，强制重抓
    writer_evidence_force_refresh: bool = False

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
