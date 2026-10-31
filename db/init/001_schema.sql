-- Схема табеля учёта времени.
-- Выполняется образом postgres при первой инициализации тома.

BEGIN;

CREATE TABLE projects (
    id            int  GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code          text NOT NULL UNIQUE,
    sessions_path text NOT NULL DEFAULT '',
    since         date NOT NULL
);

CREATE TABLE time_entries (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    work_date          date  NOT NULL,
    task_key           text  NULL CHECK (task_key ~ '^[A-Z]+-[0-9]+$'),
    label              text  NULL,
    hours              numeric(5,2) NOT NULL CHECK (hours > 0 AND hours * 4 = trunc(hours * 4)),
    description        text  NOT NULL DEFAULT '',
    estimate_source    text  NOT NULL DEFAULT '',
    tracker_state      text  NOT NULL DEFAULT 'pending'
                       CHECK (tracker_state IN ('synced', 'excluded', 'pending')),
    tracker_worklog_id bigint NULL,
    project_id         int   NULL REFERENCES projects(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CHECK (task_key IS NOT NULL OR label IS NOT NULL)
);

-- Уникальность выражением (UNIQUE-ограничение в DDL таблицы так не задаётся);
-- по этому индексу работает ON CONFLICT при импорте.
CREATE UNIQUE INDEX uq_time_entries_day_key
    ON time_entries (work_date, COALESCE(task_key, label));

CREATE INDEX idx_time_entries_work_date     ON time_entries (work_date);
CREATE INDEX idx_time_entries_task_key      ON time_entries (task_key);
CREATE INDEX idx_time_entries_project_id    ON time_entries (project_id);
CREATE INDEX idx_time_entries_tracker_state ON time_entries (tracker_state);

-- «История синхронизации» из шапки TIMESHEET.md, одной строкой.
CREATE TABLE sync_log (
    id          int PRIMARY KEY CHECK (id = 1),
    text        text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);

-- Итоги по дням.
CREATE VIEW v_daily_totals AS
SELECT work_date, sum(hours) AS hours, count(*) AS entries
FROM time_entries
GROUP BY work_date;

-- Итоги по задачам; включает строку без задачи (label), чтобы сумма сходилась
-- с «Всего» табеля.
CREATE VIEW v_task_totals AS
SELECT COALESCE(task_key, label) AS task,
       split_part(task_key, '-', 1) AS queue,
       sum(hours) AS hours,
       count(*)   AS entries
FROM time_entries
GROUP BY 1, 2;

-- Отчёт по задаче (параметризованный «view»).
CREATE FUNCTION v_task_report(p_task text)
RETURNS TABLE (task text, work_date date, hours numeric, description text)
LANGUAGE sql STABLE
AS $$
    SELECT COALESCE(te.task_key, te.label), te.work_date, te.hours, te.description
    FROM time_entries te
    WHERE COALESCE(te.task_key, te.label) = p_task
    ORDER BY te.work_date
$$;

COMMIT;
