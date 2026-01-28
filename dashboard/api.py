"""
CSR Breaktime Dashboard - REST API
FastAPI backend serving dashboard data.
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

# Philippine Timezone (UTC+8)
PH_TIMEZONE = timezone(timedelta(hours=8))

def get_ph_now():
    """Get current datetime in Philippine timezone."""
    return datetime.now(PH_TIMEZONE)

def get_ph_date():
    """Get current date in Philippine timezone."""
    return get_ph_now().date()
from typing import Optional, List
from dataclasses import asdict

# Setup path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('BASE_DIR', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Static files directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

from dashboard.aggregations import (
    get_realtime_dashboard_metrics,
    get_active_breaks_list,
    get_overdue_breaks_list,
    get_break_distribution_today,
    get_break_distribution_for_period,
    get_agent_performance_today,
    get_agent_detail,
    get_hourly_distribution_today,
    get_peak_hours,
    get_compliance_trend,
    get_compliance_summary,
    get_full_dashboard_data,
    generate_daily_report,
    generate_weekly_report,
)
from database.db import get_connection, get_all_break_types, init_database

# ============================================
# APP SETUP
# ============================================

app = FastAPI(
    title="CSR Breaktime Dashboard API",
    description="REST API for CSR Break Time Tracking Dashboard",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS - allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    try:
        init_database()
        print("Database initialized successfully")
    except Exception as e:
        print(f"Database initialization error: {e}")


# ============================================
# HEALTH & INFO
# ============================================

@app.get("/", tags=["Dashboard"], include_in_schema=False)
async def root():
    """Serve the dashboard."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "status": "ok",
        "service": "CSR Breaktime Dashboard API",
        "version": "1.0.0",
        "message": "Dashboard UI not found. API is running.",
        "docs": "/docs"
    }


@app.get("/login", tags=["Dashboard"], include_in_schema=False)
async def login_page():
    """Serve the login page."""
    login_path = os.path.join(STATIC_DIR, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return {"message": "Login page not found"}


@app.get("/history", tags=["Dashboard"], include_in_schema=False)
async def history_page():
    """Serve the history page."""
    history_path = os.path.join(STATIC_DIR, "history.html")
    if os.path.exists(history_path):
        return FileResponse(history_path)
    return {"message": "History page not found"}


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check."""
    try:
        with get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM break_logs")
            count = cursor.fetchone()[0]
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {str(e)}"
        count = 0

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "database": db_status,
        "records": count,
        "timestamp": get_ph_now().isoformat()
    }


@app.post("/api/init-db", tags=["Admin"])
async def initialize_database():
    """Manually initialize the database schema."""
    try:
        result = init_database()
        return {"status": "ok", "message": "Database initialized successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ImportDataRequest(BaseModel):
    """Request model for data import."""
    sql_statements: List[str]
    clear_existing: bool = False


@app.post("/api/migrate-data", tags=["Admin"])
async def migrate_data(request: ImportDataRequest):
    """Import data from SQL statements - used for data migration."""
    try:
        with get_connection() as conn:
            if request.clear_existing:
                # Clear existing data (preserve schema)
                tables = ['break_logs', 'active_sessions', 'daily_summaries',
                         'hourly_metrics', 'audit_log', 'compliance_alerts',
                         'team_daily_summaries', 'users']
                for table in tables:
                    try:
                        conn.execute(f"DELETE FROM {table}")
                    except:
                        pass

            executed = 0
            errors = []
            for stmt in request.sql_statements:
                stmt = stmt.strip()
                if not stmt or stmt.startswith('--'):
                    continue
                # Only allow INSERT statements for safety
                if stmt.upper().startswith('INSERT'):
                    try:
                        conn.execute(stmt)
                        executed += 1
                    except Exception as e:
                        errors.append(f"{str(e)[:50]}: {stmt[:50]}...")

            conn.commit()

        return {
            "status": "ok",
            "executed": executed,
            "errors": errors[:10] if errors else []
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# REAL-TIME DASHBOARD
# ============================================

@app.get("/api/dashboard", tags=["Dashboard"])
async def get_dashboard():
    """Get complete dashboard data in one call."""
    try:
        data = get_full_dashboard_data()
        return JSONResponse(content=data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/realtime", tags=["Dashboard"])
async def get_realtime():
    """Get real-time metrics for dashboard header."""
    try:
        metrics = get_realtime_dashboard_metrics()
        return metrics.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# ACTIVE BREAKS
# ============================================

@app.get("/api/breaks/active", tags=["Breaks"])
async def get_active_breaks():
    """Get all currently active breaks."""
    try:
        breaks = get_active_breaks_list()
        return {
            "count": len(breaks),
            "breaks": [asdict(b) for b in breaks]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/breaks/overdue", tags=["Breaks"])
async def get_overdue_breaks():
    """Get breaks that are over their time limit."""
    try:
        breaks = get_overdue_breaks_list()
        return {
            "count": len(breaks),
            "breaks": [asdict(b) for b in breaks]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# BREAK DISTRIBUTION
# ============================================

@app.get("/api/distribution/today", tags=["Distribution"])
async def get_distribution_today():
    """Get break distribution by type for today."""
    try:
        dist = get_break_distribution_today()
        return {
            "date": str(get_ph_date()),
            "distribution": [asdict(d) for d in dist]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/distribution/period", tags=["Distribution"])
async def get_distribution_period(
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)")
):
    """Get break distribution for a date range."""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        dist = get_break_distribution_for_period(start_date, end_date)
        return {
            "start": start,
            "end": end,
            "distribution": [asdict(d) for d in dist]
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# AGENT PERFORMANCE
# ============================================

@app.get("/api/agents", tags=["Agents"])
async def get_agents_performance():
    """Get performance metrics for all agents today."""
    try:
        agents = get_agent_performance_today()
        return {
            "date": str(get_ph_date()),
            "count": len(agents),
            "agents": [asdict(a) for a in agents]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agents/{user_id}", tags=["Agents"])
async def get_agent_details(
    user_id: int,
    days: int = Query(7, ge=1, le=30, description="Days of history")
):
    """Get detailed metrics for a specific agent."""
    try:
        detail = get_agent_detail(user_id, days)
        if not detail.get('user'):
            raise HTTPException(status_code=404, detail="Agent not found")
        return detail
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# HOURLY ANALYSIS
# ============================================

@app.get("/api/hourly/today", tags=["Hourly"])
async def get_hourly_today():
    """Get hourly break distribution for today."""
    try:
        hourly = get_hourly_distribution_today()
        return {
            "date": str(get_ph_date()),
            "hourly": [asdict(h) for h in hourly]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/hourly/peaks", tags=["Hourly"])
async def get_peak_times(
    days: int = Query(7, ge=1, le=30, description="Days to analyze"),
    top: int = Query(5, ge=1, le=24, description="Number of peak hours")
):
    """Get peak break hours over a period."""
    try:
        peaks = get_peak_hours(days, top)
        return {
            "days_analyzed": days,
            "peaks": peaks
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# COMPLIANCE
# ============================================

@app.get("/api/compliance/today", tags=["Compliance"])
async def get_compliance_today():
    """Get compliance metrics for today."""
    try:
        with get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE
                        WHEN bl.duration_minutes <= bt.time_limit_minutes THEN 1
                        WHEN bt.time_limit_minutes IS NULL THEN 1
                        ELSE 0
                    END) as within_limit,
                    SUM(CASE
                        WHEN bt.time_limit_minutes IS NOT NULL AND bl.duration_minutes > bt.time_limit_minutes THEN 1
                        ELSE 0
                    END) as over_limit
                FROM break_logs bl
                JOIN break_types bt ON bl.break_type_id = bt.id
                WHERE bl.log_date = DATE('now') AND bl.action = 'BACK'
            """)
            row = cursor.fetchone()

        total = row['total'] or 0
        within = row['within_limit'] or 0
        over = row['over_limit'] or 0
        rate = round(100 * within / total, 1) if total > 0 else 100.0

        return {
            "date": str(get_ph_date()),
            "total_breaks": total,
            "within_limit": within,
            "over_limit": over,
            "compliance_rate": rate
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/compliance/trend", tags=["Compliance"])
async def get_compliance_trend_data(
    days: int = Query(7, ge=1, le=90, description="Days of trend data")
):
    """Get compliance trend over time."""
    try:
        trend = get_compliance_trend(days)
        return {
            "days": days,
            "trend": [asdict(t) for t in trend]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/compliance/summary", tags=["Compliance"])
async def get_compliance_summary_data(
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)")
):
    """Get compliance summary for a date range."""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
        summary = get_compliance_summary(start_date, end_date)
        return summary
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# REPORTS
# ============================================

@app.get("/api/reports/daily", tags=["Reports"])
async def get_daily_report(
    report_date: Optional[str] = Query(None, description="Date (YYYY-MM-DD), defaults to today")
):
    """Generate daily report."""
    try:
        if report_date:
            dt = datetime.strptime(report_date, "%Y-%m-%d").date()
        else:
            dt = get_ph_date()
        report = generate_daily_report(dt)
        return report
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/weekly", tags=["Reports"])
async def get_weekly_report(
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD), defaults to today")
):
    """Generate weekly report."""
    try:
        if end_date:
            dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        else:
            dt = get_ph_date()
        report = generate_weekly_report(dt)
        return report
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# REFERENCE DATA
# ============================================

@app.get("/api/break-types", tags=["Reference"])
async def get_break_types():
    """Get all break types with their limits."""
    try:
        types = get_all_break_types()
        return {"break_types": types}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# HISTORICAL DATA
# ============================================

@app.get("/api/history/logs", tags=["History"])
async def get_break_logs(
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    break_type: Optional[str] = Query(None, description="Filter by break type code (B/W/P/O)"),
    limit: int = Query(100, ge=1, le=1000, description="Max records"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """Get historical break logs with filters."""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        query = """
            SELECT
                bl.id, bl.timestamp, bl.action, bl.duration_minutes, bl.reason,
                u.full_name, u.telegram_id,
                bt.display_name as break_type, bt.code as break_type_code
            FROM break_logs bl
            JOIN users u ON bl.user_id = u.id
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date BETWEEN ? AND ?
        """
        params = [str(start_date), str(end_date)]

        if user_id:
            query += " AND u.id = ?"
            params.append(user_id)

        if break_type:
            query += " AND bt.code = ?"
            params.append(break_type.upper())

        query += " ORDER BY bl.timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with get_connection() as conn:
            cursor = conn.execute(query, params)
            logs = [dict(row) for row in cursor.fetchall()]

            # Get total count
            count_query = """
                SELECT COUNT(*) FROM break_logs bl
                JOIN break_types bt ON bl.break_type_id = bt.id
                WHERE bl.log_date BETWEEN ? AND ?
            """
            count_params = [str(start_date), str(end_date)]
            if user_id:
                count_query += " AND bl.user_id = ?"
                count_params.append(user_id)
            if break_type:
                count_query += " AND bt.code = ?"
                count_params.append(break_type.upper())

            cursor = conn.execute(count_query, count_params)
            total = cursor.fetchone()[0]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "logs": logs
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# USERS
# ============================================

@app.get("/api/users", tags=["Users"])
async def get_users(
    active_only: bool = Query(True, description="Only show recently active users")
):
    """Get all users."""
    try:
        with get_connection() as conn:
            if active_only:
                cursor = conn.execute("""
                    SELECT * FROM users
                    WHERE last_active_at >= DATE('now', '-7 days')
                    ORDER BY full_name
                """)
            else:
                cursor = conn.execute("SELECT * FROM users ORDER BY full_name")
            users = [dict(row) for row in cursor.fetchall()]

        return {
            "count": len(users),
            "users": users
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# WEBSOCKET
# ============================================

from dashboard.websocket import manager, websocket_endpoint
from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    # Log connection attempt details
    client = websocket.client
    headers = dict(websocket.headers) if hasattr(websocket, 'headers') else {}
    print(f"[WS] Connection attempt from {client}, headers: {list(headers.keys())}")

    try:
        await websocket_endpoint(websocket)
    except WebSocketDisconnect:
        print("[WS] Client disconnected normally")
    except Exception as e:
        print(f"[WS] WebSocket error: {type(e).__name__}: {e}")

def cleanup_stale_sessions(max_minutes: int = 120):
    """Remove active sessions older than max_minutes (default 2 hours)."""
    try:
        with get_connection() as conn:
            cursor = conn.execute('''
                DELETE FROM active_sessions
                WHERE (julianday(datetime('now', '+8 hours')) - julianday(start_time)) * 24 * 60 > ?
            ''', (max_minutes,))
            deleted = cursor.rowcount
            if deleted > 0:
                print(f"[Cleanup] Removed {deleted} stale sessions (>{max_minutes}m old)")
            return deleted
    except Exception as e:
        print(f"[Cleanup Error] {e}")
        return 0

async def periodic_cleanup(interval_seconds: int = 300):
    """Run cleanup every interval_seconds (default 5 minutes)."""
    import asyncio
    while True:
        await asyncio.sleep(interval_seconds)
        cleanup_stale_sessions()

@app.on_event("startup")
async def startup_event():
    """Start background tasks on startup."""
    import asyncio
    # Clean up stale sessions on startup
    cleanup_stale_sessions()
    # Start periodic cleanup (every 5 minutes)
    asyncio.create_task(periodic_cleanup(300))
    # Start WebSocket broadcast loop
    asyncio.create_task(manager.start_broadcast_loop(10))


# ============================================
# ALERTS
# ============================================

from dashboard.alerts import get_alert_endpoints, alert_manager
from dashboard.auth import get_auth_router

app.include_router(get_alert_endpoints())
app.include_router(get_auth_router())


# ============================================
# EXPORT
# ============================================

from fastapi.responses import StreamingResponse
import io
import csv

@app.get("/api/export/csv", tags=["Export"])
async def export_csv(
    start: str = Query(..., description="Start date (YYYY-MM-DD)"),
    end: str = Query(..., description="End date (YYYY-MM-DD)"),
    user_id: Optional[int] = Query(None, description="Filter by user ID")
):
    """Export break logs as CSV."""
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()

        query = """
            SELECT
                bl.timestamp, u.full_name, u.telegram_id,
                bt.display_name as break_type, bl.action,
                bl.duration_minutes, bl.reason
            FROM break_logs bl
            JOIN users u ON bl.user_id = u.id
            JOIN break_types bt ON bl.break_type_id = bt.id
            WHERE bl.log_date BETWEEN ? AND ?
        """
        params = [str(start_date), str(end_date)]

        if user_id:
            query += " AND u.id = ?"
            params.append(user_id)

        query += " ORDER BY bl.timestamp"

        with get_connection() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp', 'Full Name', 'Telegram ID', 'Break Type', 'Action', 'Duration (min)', 'Reason'])

        for row in rows:
            writer.writerow([
                row['timestamp'],
                row['full_name'],
                row['telegram_id'],
                row['break_type'],
                row['action'],
                row['duration_minutes'] or '',
                row['reason'] or ''
            ])

        output.seek(0)
        filename = f"break_logs_{start}_{end}.csv"

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/report", tags=["Export"])
async def export_report(
    report_type: str = Query("daily", description="Report type: daily or weekly"),
    report_date: Optional[str] = Query(None, description="Date (YYYY-MM-DD)")
):
    """Export report as JSON file."""
    try:
        if report_date:
            dt = datetime.strptime(report_date, "%Y-%m-%d").date()
        else:
            dt = get_ph_date()

        if report_type == "weekly":
            report = generate_weekly_report(dt)
            filename = f"weekly_report_{dt}.json"
        else:
            report = generate_daily_report(dt)
            filename = f"daily_report_{dt}.json"

        import json
        output = json.dumps(report, indent=2, default=str)

        return StreamingResponse(
            iter([output]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# RUN SERVER
# ============================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
