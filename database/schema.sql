-- CSR Breaktime Dashboard Database Schema
-- SQLite compatible (can migrate to PostgreSQL)
-- Designed for efficient dashboard queries and analytics

-- ============================================
-- CORE TABLES
-- ============================================

-- Users table: Normalized user information
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    full_name TEXT NOT NULL,
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_active_at TIMESTAMP,
    is_active BOOLEAN DEFAULT 1,
    role TEXT DEFAULT 'agent' CHECK (role IN ('agent', 'supervisor', 'admin')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

-- Break types reference table
CREATE TABLE IF NOT EXISTS break_types (
    id INTEGER PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,        -- B, W, P, O
    name TEXT NOT NULL,               -- Break, WC, WCP, Other
    display_name TEXT NOT NULL,       -- ☕ Break, 🚻 WC, etc.
    time_limit_minutes INTEGER,       -- 30, 5, 10, NULL
    requires_reason BOOLEAN DEFAULT 0,
    is_counted_in_total BOOLEAN DEFAULT 1,  -- WC excluded from totals
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed break types
INSERT OR IGNORE INTO break_types (code, name, display_name, time_limit_minutes, requires_reason, is_counted_in_total) VALUES
    ('B', 'Break', '☕ Break', 30, 0, 1),
    ('W', 'WC', '🚻 WC', 5, 0, 0),
    ('P', 'WCP', '🚽 WCP', 10, 0, 1),
    ('O', 'Other', '⚠️ Other', NULL, 1, 1);

-- Break logs: Main activity log (replaces Excel)
CREATE TABLE IF NOT EXISTS break_logs (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    break_type_id INTEGER NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('OUT', 'BACK')),
    timestamp TIMESTAMP NOT NULL,
    duration_minutes REAL,            -- Only for BACK actions
    reason TEXT,                      -- For 'Other' breaks
    group_chat_id INTEGER,            -- Telegram group where action occurred
    log_date DATE NOT NULL,           -- Extracted for efficient date queries
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (break_type_id) REFERENCES break_types(id)
);

CREATE INDEX IF NOT EXISTS idx_break_logs_user_id ON break_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_break_logs_log_date ON break_logs(log_date);
CREATE INDEX IF NOT EXISTS idx_break_logs_timestamp ON break_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_break_logs_action ON break_logs(action);
CREATE INDEX IF NOT EXISTS idx_break_logs_user_date ON break_logs(user_id, log_date);

-- Active sessions: Current active breaks (replaces in-memory dict)
CREATE TABLE IF NOT EXISTS active_sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL,
    break_type_id INTEGER NOT NULL,
    start_time TIMESTAMP NOT NULL,
    reason TEXT,
    group_chat_id INTEGER,
    reminder_sent BOOLEAN DEFAULT 0,
    last_reminder_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (break_type_id) REFERENCES break_types(id)
);

CREATE INDEX IF NOT EXISTS idx_active_sessions_user_id ON active_sessions(user_id);

-- ============================================
-- ANALYTICS & DASHBOARD TABLES
-- ============================================

-- Daily summaries: Pre-computed daily aggregations per user
CREATE TABLE IF NOT EXISTS daily_summaries (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    summary_date DATE NOT NULL,

    -- Break counts by type
    break_count INTEGER DEFAULT 0,
    wc_count INTEGER DEFAULT 0,
    wcp_count INTEGER DEFAULT 0,
    other_count INTEGER DEFAULT 0,
    total_breaks INTEGER DEFAULT 0,

    -- Duration totals (minutes)
    break_duration_total REAL DEFAULT 0,
    wc_duration_total REAL DEFAULT 0,
    wcp_duration_total REAL DEFAULT 0,
    other_duration_total REAL DEFAULT 0,
    total_duration REAL DEFAULT 0,           -- Excludes WC
    total_duration_all REAL DEFAULT 0,       -- Includes all types

    -- Average durations
    break_duration_avg REAL,
    wc_duration_avg REAL,
    wcp_duration_avg REAL,
    other_duration_avg REAL,

    -- Compliance metrics
    breaks_within_limit INTEGER DEFAULT 0,
    breaks_over_limit INTEGER DEFAULT 0,
    compliance_rate REAL,                    -- Percentage 0-100
    max_overdue_minutes REAL,                -- Worst violation

    -- Missing clock-backs
    missing_clock_backs INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(user_id, summary_date),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_daily_summaries_date ON daily_summaries(summary_date);
CREATE INDEX IF NOT EXISTS idx_daily_summaries_user_date ON daily_summaries(user_id, summary_date);

-- Team daily summaries: Aggregated team metrics per day
CREATE TABLE IF NOT EXISTS team_daily_summaries (
    id INTEGER PRIMARY KEY,
    summary_date DATE UNIQUE NOT NULL,

    -- Headcount
    total_agents INTEGER DEFAULT 0,
    agents_with_breaks INTEGER DEFAULT 0,

    -- Total metrics
    total_breaks INTEGER DEFAULT 0,
    total_duration_minutes REAL DEFAULT 0,

    -- By type totals
    break_total_count INTEGER DEFAULT 0,
    wc_total_count INTEGER DEFAULT 0,
    wcp_total_count INTEGER DEFAULT 0,
    other_total_count INTEGER DEFAULT 0,

    -- Compliance
    team_compliance_rate REAL,
    total_overdue_incidents INTEGER DEFAULT 0,

    -- Peak hours (JSON: {"09": 5, "12": 15, ...})
    peak_hours_distribution TEXT,

    -- Alerts
    total_alerts_sent INTEGER DEFAULT 0,
    missing_clock_backs INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_team_daily_date ON team_daily_summaries(summary_date);

-- Compliance alerts: Historical record of all alerts sent
CREATE TABLE IF NOT EXISTS compliance_alerts (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    break_log_id INTEGER,              -- Links to the OUT log entry
    break_type_id INTEGER NOT NULL,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('overdue', 'missing_back', 'daily_summary')),
    alert_timestamp TIMESTAMP NOT NULL,
    duration_at_alert REAL,            -- Minutes at time of alert
    over_limit_minutes REAL,           -- How much over the limit
    message_sent TEXT,                 -- The alert message content
    sent_to_group BOOLEAN DEFAULT 0,
    sent_to_user BOOLEAN DEFAULT 0,
    acknowledged BOOLEAN DEFAULT 0,
    acknowledged_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (break_log_id) REFERENCES break_logs(id),
    FOREIGN KEY (break_type_id) REFERENCES break_types(id)
);

CREATE INDEX IF NOT EXISTS idx_compliance_alerts_user ON compliance_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_compliance_alerts_date ON compliance_alerts(alert_timestamp);
CREATE INDEX IF NOT EXISTS idx_compliance_alerts_type ON compliance_alerts(alert_type);

-- Hourly metrics: For peak time analysis
CREATE TABLE IF NOT EXISTS hourly_metrics (
    id INTEGER PRIMARY KEY,
    metric_date DATE NOT NULL,
    hour INTEGER NOT NULL CHECK (hour >= 0 AND hour <= 23),

    break_outs INTEGER DEFAULT 0,
    break_backs INTEGER DEFAULT 0,
    active_breaks_peak INTEGER DEFAULT 0,

    UNIQUE(metric_date, hour)
);

CREATE INDEX IF NOT EXISTS idx_hourly_metrics_date ON hourly_metrics(metric_date);

-- ============================================
-- CONFIGURATION & SYSTEM TABLES
-- ============================================

-- System configuration
CREATE TABLE IF NOT EXISTS system_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed default configuration
INSERT OR IGNORE INTO system_config (key, value, description) VALUES
    ('timezone', 'Asia/Manila', 'System timezone for all timestamps'),
    ('reminder_interval_seconds', '60', 'How often to check for overdue breaks'),
    ('daily_report_hour', '0', 'Hour to send daily reports (0-23)'),
    ('group_chat_id', '', 'Telegram group for reports'),
    ('dashboard_refresh_seconds', '30', 'Dashboard auto-refresh interval');

-- Audit log for tracking changes
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_id INTEGER,
    action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values TEXT,                   -- JSON of old values
    new_values TEXT,                   -- JSON of new values
    user_id INTEGER,                   -- Who made the change
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_audit_log_table ON audit_log(table_name);
CREATE INDEX IF NOT EXISTS idx_audit_log_date ON audit_log(created_at);

-- ============================================
-- VIEWS FOR DASHBOARD QUERIES
-- ============================================

-- View: Current active breaks with user details
CREATE VIEW IF NOT EXISTS v_active_breaks AS
SELECT
    s.id AS session_id,
    u.telegram_id,
    u.username,
    u.full_name,
    bt.display_name AS break_type,
    bt.time_limit_minutes,
    s.start_time,
    s.reason,
    ROUND((julianday('now') - julianday(s.start_time)) * 24 * 60, 1) AS duration_minutes,
    CASE
        WHEN bt.time_limit_minutes IS NOT NULL
             AND (julianday('now') - julianday(s.start_time)) * 24 * 60 > bt.time_limit_minutes
        THEN 1 ELSE 0
    END AS is_overdue,
    CASE
        WHEN bt.time_limit_minutes IS NOT NULL
        THEN ROUND((julianday('now') - julianday(s.start_time)) * 24 * 60 - bt.time_limit_minutes, 1)
        ELSE NULL
    END AS minutes_over_limit,
    s.reminder_sent
FROM active_sessions s
JOIN users u ON s.user_id = u.id
JOIN break_types bt ON s.break_type_id = bt.id;

-- View: Today's break summary by user
CREATE VIEW IF NOT EXISTS v_today_user_summary AS
SELECT
    u.id AS user_id,
    u.telegram_id,
    u.full_name,
    bt.display_name AS break_type,
    COUNT(CASE WHEN bl.action = 'OUT' THEN 1 END) AS out_count,
    COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) AS back_count,
    COALESCE(SUM(bl.duration_minutes), 0) AS total_duration,
    COALESCE(AVG(bl.duration_minutes), 0) AS avg_duration,
    COUNT(CASE WHEN bl.action = 'OUT' THEN 1 END) -
        COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) AS missing_backs
FROM users u
LEFT JOIN break_logs bl ON u.id = bl.user_id AND bl.log_date = DATE('now')
LEFT JOIN break_types bt ON bl.break_type_id = bt.id
GROUP BY u.id, bt.id;

-- View: Real-time dashboard metrics
CREATE VIEW IF NOT EXISTS v_dashboard_realtime AS
SELECT
    (SELECT COUNT(*) FROM active_sessions) AS active_breaks,
    (SELECT COUNT(*) FROM v_active_breaks WHERE is_overdue = 1) AS overdue_breaks,
    (SELECT COUNT(DISTINCT user_id) FROM break_logs WHERE log_date = DATE('now')) AS agents_active_today,
    (SELECT COUNT(*) FROM break_logs WHERE log_date = DATE('now') AND action = 'BACK') AS completed_breaks_today,
    (SELECT COALESCE(SUM(duration_minutes), 0) FROM break_logs bl
     JOIN break_types bt ON bl.break_type_id = bt.id
     WHERE log_date = DATE('now') AND action = 'BACK' AND bt.is_counted_in_total = 1) AS total_break_time_today;

-- View: Compliance summary for today
CREATE VIEW IF NOT EXISTS v_compliance_today AS
SELECT
    COUNT(*) AS total_completed_breaks,
    SUM(CASE
        WHEN bl.duration_minutes <= bt.time_limit_minutes THEN 1
        WHEN bt.time_limit_minutes IS NULL THEN 1
        ELSE 0
    END) AS within_limit,
    SUM(CASE
        WHEN bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes > bt.time_limit_minutes THEN 1
        ELSE 0
    END) AS over_limit,
    ROUND(
        100.0 * SUM(CASE
            WHEN bl.duration_minutes <= bt.time_limit_minutes THEN 1
            WHEN bt.time_limit_minutes IS NULL THEN 1
            ELSE 0
        END) / NULLIF(COUNT(*), 0), 1
    ) AS compliance_rate
FROM break_logs bl
JOIN break_types bt ON bl.break_type_id = bt.id
WHERE bl.log_date = DATE('now') AND bl.action = 'BACK';

-- ============================================
-- TRIGGERS FOR AUTOMATIC UPDATES
-- ============================================

-- Trigger: Update user last_active_at on break log
CREATE TRIGGER IF NOT EXISTS trg_update_user_activity
AFTER INSERT ON break_logs
BEGIN
    UPDATE users
    SET last_active_at = NEW.timestamp, updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.user_id;
END;

-- Trigger: Update hourly metrics on break log
CREATE TRIGGER IF NOT EXISTS trg_update_hourly_metrics
AFTER INSERT ON break_logs
BEGIN
    INSERT INTO hourly_metrics (metric_date, hour, break_outs, break_backs)
    VALUES (
        NEW.log_date,
        CAST(strftime('%H', NEW.timestamp) AS INTEGER),
        CASE WHEN NEW.action = 'OUT' THEN 1 ELSE 0 END,
        CASE WHEN NEW.action = 'BACK' THEN 1 ELSE 0 END
    )
    ON CONFLICT(metric_date, hour) DO UPDATE SET
        break_outs = break_outs + CASE WHEN NEW.action = 'OUT' THEN 1 ELSE 0 END,
        break_backs = break_backs + CASE WHEN NEW.action = 'BACK' THEN 1 ELSE 0 END;
END;
