-- ============================================================
-- data-to-article MySQL 存储表结构（MySqlBackend）
-- 要求：MySQL 5.7+（JSON 类型）；字符集 utf8mb4
-- 用法：
--   mysql -u root -p < schema.sql
-- 表前缀默认 dta_；MySqlBackend 首次连接也会自动建库建表（幂等）
-- ============================================================

CREATE DATABASE IF NOT EXISTS data_to_article
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE data_to_article;

-- 原始数据（ingest 写入，清洗读取）
CREATE TABLE IF NOT EXISTS dta_raw (
  id         VARCHAR(64) PRIMARY KEY,
  doc        JSON NOT NULL,
  pub_time   VARCHAR(64),
  source     VARCHAR(255),
  stored_at  VARCHAR(64),
  KEY idx_raw_pub (pub_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 清洗库：清洗后文章（按 content_fp 幂等 upsert）
CREATE TABLE IF NOT EXISTS dta_cleaned (
  content_fp VARCHAR(64) PRIMARY KEY,
  doc        JSON NOT NULL,
  cleaned_at VARCHAR(64),
  source     VARCHAR(255),
  KEY idx_cleaned_at (cleaned_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 查重指纹（归类侧原子认领）
CREATE TABLE IF NOT EXISTS dta_dedup (
  content_fp  VARCHAR(64) PRIMARY KEY,
  event_id    VARCHAR(64) NOT NULL DEFAULT '',
  status      VARCHAR(16) NOT NULL DEFAULT 'pending',   -- pending / assigned
  claimed_at  VARCHAR(64),
  assigned_at VARCHAR(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 归类库：事件（event_title / keywords 冗余列用于 LIKE 搜索）
CREATE TABLE IF NOT EXISTS dta_events (
  event_id    VARCHAR(64) PRIMARY KEY,
  doc         JSON NOT NULL,
  event_title VARCHAR(512),
  keywords    TEXT,
  updated_at  VARCHAR(64),
  KEY idx_events_updated (updated_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 二创库：每事件的多视角文章 + 版本归档（doc 内含 articles / versions）
CREATE TABLE IF NOT EXISTS dta_articles (
  event_id        VARCHAR(64) PRIMARY KEY,
  doc             JSON NOT NULL,
  ai_generated_at VARCHAR(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 运行记录
CREATE TABLE IF NOT EXISTS dta_runs (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  stage       VARCHAR(32),
  status      VARCHAR(16),
  params      JSON,
  log_tail    TEXT,
  started_at  VARCHAR(64),
  finished_at VARCHAR(64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;