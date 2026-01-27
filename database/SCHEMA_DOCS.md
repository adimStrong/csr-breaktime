# CSR Breaktime Database Schema Documentation

## Entity-Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           CSR BREAKTIME DATABASE SCHEMA                             │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐         ┌──────────────────┐         ┌─────────────────────┐
│     users       │         │   break_types    │         │   system_config     │
├─────────────────┤         ├──────────────────┤         ├─────────────────────┤
│ PK id           │         │ PK id            │         │ PK key              │
│    telegram_id  │◄───┐    │    code          │◄──┐     │    value            │
│    username     │    │    │    name          │   │     │    description      │
│    full_name    │    │    │    display_name  │   │     │    updated_at       │
│    first_seen   │    │    │    time_limit    │   │     └─────────────────────┘
│    last_active  │    │    │    requires_rsn  │   │
│    is_active    │    │    │    is_counted    │   │
│    role         │    │    └──────────────────┘   │
└─────────────────┘    │                           │
         │             │                           │
         │             │                           │
         ▼             │                           │
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    break_logs                                        │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ PK id                                                                               │
│ FK user_id ────────────────────────────────────────────────────────────────────────►│
│ FK break_type_id ──────────────────────────────────────────────────────────────────►│
│    action (OUT/BACK)                                                                │
│    timestamp                                                                         │
│    duration_minutes (BACK only)                                                     │
│    reason                                                                            │
│    group_chat_id                                                                     │
│    log_date                                                                          │
└─────────────────────────────────────────────────────────────────────────────────────┘
         │
         │ Aggregates to
         ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  daily_summaries                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ PK id                                                                               │
│ FK user_id                                                                          │
│    summary_date                                                                      │
│    break_count, wc_count, wcp_count, other_count, total_breaks                     │
│    break_duration_total, wc_duration_total, wcp_duration_total, other_duration     │
│    total_duration (excl WC), total_duration_all                                     │
│    break_duration_avg, wc_duration_avg, wcp_duration_avg, other_duration_avg       │
│    breaks_within_limit, breaks_over_limit, compliance_rate                          │
│    max_overdue_minutes, missing_clock_backs                                         │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  active_sessions                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ PK id                                                                               │
│ FK user_id (UNIQUE - one active session per user)                                   │
│ FK break_type_id                                                                    │
│    start_time                                                                        │
│    reason                                                                            │
│    group_chat_id                                                                     │
│    reminder_sent                                                                     │
│    last_reminder_at                                                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                compliance_alerts                                     │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ PK id                                                                               │
│ FK user_id                                                                          │
│ FK break_log_id                                                                     │
│ FK break_type_id                                                                    │
│    alert_type (overdue/missing_back/daily_summary)                                  │
│    alert_timestamp                                                                   │
│    duration_at_alert                                                                 │
│    over_limit_minutes                                                                │
│    message_sent                                                                      │
│    sent_to_group, sent_to_user, acknowledged                                        │
└─────────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                  hourly_metrics                                      │
├─────────────────────────────────────────────────────────────────────────────────────┤
│ PK id                                                                               │
│    metric_date                                                                       │
│    hour (0-23)                                                                       │
│    break_outs                                                                        │
│    break_backs                                                                       │
│    active_breaks_peak                                                                │
│    UNIQUE(metric_date, hour)                                                         │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

## Table Descriptions

### Core Tables

| Table | Purpose | Key Features |
|-------|---------|--------------|
| `users` | Stores all CSR agent information | Telegram ID, role-based access, activity tracking |
| `break_types` | Reference table for break categories | Time limits, display names, compliance rules |
| `break_logs` | Main activity log (replaces Excel) | Every OUT/BACK action with timestamps |
| `active_sessions` | Currently active breaks | Real-time tracking, reminder state |

### Analytics Tables

| Table | Purpose | Update Frequency |
|-------|---------|------------------|
| `daily_summaries` | Pre-computed daily metrics per user | End of day / on demand |
| `team_daily_summaries` | Aggregated team metrics | End of day |
| `hourly_metrics` | Peak time analysis | Triggered on each break log |
| `compliance_alerts` | Historical alert records | On each alert sent |

### System Tables

| Table | Purpose |
|-------|---------|
| `system_config` | Key-value configuration store |
| `audit_log` | Change tracking for compliance |

## Views (Pre-built Queries)

| View | Purpose | Use Case |
|------|---------|----------|
| `v_active_breaks` | Active sessions with user details | Real-time dashboard panel |
| `v_today_user_summary` | Today's summary by user/type | Agent performance table |
| `v_dashboard_realtime` | Single-row real-time metrics | Dashboard header stats |
| `v_compliance_today` | Compliance rate for today | Compliance gauge |

## Break Types Reference

| Code | Display Name | Time Limit | Counted in Total |
|------|--------------|------------|------------------|
| B | ☕ Break | 30 min | Yes |
| W | 🚻 WC | 5 min | No |
| P | 🚽 WCP | 10 min | Yes |
| O | ⚠️ Other | None | Yes |

## Sample Dashboard Queries

### 1. Real-Time Overview
```sql
SELECT * FROM v_dashboard_realtime;
-- Returns: active_breaks, overdue_breaks, agents_active_today, completed_breaks_today, total_break_time_today
```

### 2. Overdue Breaks Alert List
```sql
SELECT * FROM v_active_breaks WHERE is_overdue = 1 ORDER BY minutes_over_limit DESC;
```

### 3. Agent Compliance Leaderboard
```sql
SELECT
    u.full_name,
    ds.total_breaks,
    ds.total_duration,
    ds.compliance_rate,
    ds.missing_clock_backs
FROM daily_summaries ds
JOIN users u ON ds.user_id = u.id
WHERE ds.summary_date = DATE('now')
ORDER BY ds.compliance_rate DESC, ds.total_breaks DESC;
```

### 4. Peak Hours Analysis
```sql
SELECT hour, SUM(break_outs) as breaks
FROM hourly_metrics
WHERE metric_date >= DATE('now', '-7 days')
GROUP BY hour
ORDER BY breaks DESC
LIMIT 5;
```

### 5. Weekly Compliance Trend
```sql
SELECT
    summary_date,
    ROUND(100.0 * SUM(breaks_within_limit) /
        NULLIF(SUM(breaks_within_limit + breaks_over_limit), 0), 1) as compliance_rate
FROM daily_summaries
WHERE summary_date >= DATE('now', '-7 days')
GROUP BY summary_date
ORDER BY summary_date;
```

## Migration Notes

- Run `migrate_excel.py` to import existing Excel data
- All timestamps stored in Philippine Time (Asia/Manila)
- Duration is calculated only for BACK actions
- WC breaks excluded from total duration calculations (matches existing logic)

## Index Strategy

| Index | Purpose |
|-------|---------|
| `idx_break_logs_user_date` | User's daily breaks lookup |
| `idx_break_logs_log_date` | Daily reports query |
| `idx_daily_summaries_date` | Trend analysis |
| `idx_compliance_alerts_date` | Alert history |
| `idx_hourly_metrics_date` | Peak time queries |
