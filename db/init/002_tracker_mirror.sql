-- Зеркало Яндекс Трекера: задачи, комментарии, вложения, история (PLAN: локальное зеркало).
-- Идемпотентно: безопасно и на свежем томе (docker-entrypoint-initdb.d), и повторно.
-- PK — стабильные ID Трекера (не меняются при переносе задачи между очередями);
-- issues.key — всегда актуальный ключ, старые ключи — в issue_aliases.

BEGIN;

CREATE TABLE IF NOT EXISTS issues (
    id             text PRIMARY KEY,
    key            text NOT NULL UNIQUE,
    summary        text NOT NULL DEFAULT '',
    description    text NOT NULL DEFAULT '',
    queue          text NOT NULL DEFAULT '',
    queue_name     text NOT NULL DEFAULT '',
    status_key     text,
    status_name    text,
    type_name      text,
    priority_name  text,
    assignee       text,
    assignee_name  text,
    created_by     text,
    created_by_name text,
    followers      jsonb NOT NULL DEFAULT '[]',
    tags           jsonb NOT NULL DEFAULT '[]',
    created_at     timestamptz,
    updated_at     timestamptz,
    resolved_at    timestamptz,
    raw            jsonb NOT NULL DEFAULT '{}',
    synced_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issues_queue       ON issues (queue);
CREATE INDEX IF NOT EXISTS idx_issues_status_key  ON issues (status_key);
CREATE INDEX IF NOT EXISTS idx_issues_updated_at  ON issues (updated_at DESC);

CREATE TABLE IF NOT EXISTS issue_comments (
    id          bigint PRIMARY KEY,
    issue_id    text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    long_id     text,
    text        text NOT NULL DEFAULT '',
    author      text,
    author_name text,
    created_at  timestamptz,
    updated_at  timestamptz,
    version     int,
    transport   text,
    type        text,
    raw         jsonb NOT NULL DEFAULT '{}',
    synced_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_comments_issue ON issue_comments (issue_id, created_at);

CREATE TABLE IF NOT EXISTS issue_attachments (
    id            bigint PRIMARY KEY,
    issue_id      text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    name          text NOT NULL,
    size          bigint NOT NULL DEFAULT 0,
    mimetype      text,
    author        text,
    created_at    timestamptz,
    content_url   text NOT NULL DEFAULT '',
    file_path     text,                    -- путь ОТНОСИТЕЛЬНО каталога вложений
    downloaded_at timestamptz,             -- NULL — метаданные есть, файла нет
    raw           jsonb NOT NULL DEFAULT '{}',
    synced_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_attachments_issue ON issue_attachments (issue_id);

CREATE TABLE IF NOT EXISTS issue_changelog (
    id          text PRIMARY KEY,               -- ID истории — hex-строка
    issue_id    text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    updated_at  timestamptz,
    author      text,
    author_name text,
    transport   text,
    type        text,
    fields      jsonb NOT NULL DEFAULT '[]',
    raw         jsonb NOT NULL DEFAULT '{}',
    synced_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_changelog_issue ON issue_changelog (issue_id, updated_at);

-- Старые ключи задачи (перенос между очередями даёт алиас).
CREATE TABLE IF NOT EXISTS issue_aliases (
    alias    text PRIMARY KEY,
    issue_id text NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
    seen_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_issue_aliases_issue ON issue_aliases (issue_id);

-- Состояние синхронизации (одна строка, паттерн sync_log).
CREATE TABLE IF NOT EXISTS sync_state (
    id                int  PRIMARY KEY CHECK (id = 1),
    last_run_at       timestamptz,
    last_mode         text,
    last_duration_sec double precision,
    issues_total      int,
    stats             jsonb NOT NULL DEFAULT '{}',
    errors            jsonb NOT NULL DEFAULT '[]',
    updated_at        timestamptz NOT NULL DEFAULT now()
);
INSERT INTO sync_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

COMMIT;
