-- Academic Agent Platform - PostgreSQL 初始化脚本
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- 预留 pgvector（可选，镜像无扩展时忽略失败）
-- CREATE EXTENSION IF NOT EXISTS vector;
