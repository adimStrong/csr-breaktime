"""
CSR Breaktime Dashboard - Compliance Alerting System
Monitors breaks and sends alerts for violations.
"""

import os
import sys
import asyncio
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.db import (
    get_connection,
    get_overdue_sessions,
    log_compliance_alert,
)


@dataclass
class Alert:
    """Alert data structure."""
    id: Optional[int]
    user_id: int
    full_name: str
    break_type: str
    alert_type: str  # 'overdue', 'missing_back', 'daily_summary'
    duration_minutes: float
    over_limit_minutes: float
    message: str
    timestamp: str
    severity: str  # 'warning', 'critical'


class AlertManager:
    """Manages compliance alerts and notifications."""

    def __init__(self):
        self.recent_alerts: List[Alert] = []
        self.alert_callbacks = []
        self._check_task = None

    def add_callback(self, callback):
        """Add callback function for new alerts."""
        self.alert_callbacks.append(callback)

    async def notify_callbacks(self, alert: Alert):
        """Notify all registered callbacks."""
        for callback in self.alert_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(alert)
                else:
                    callback(alert)
            except Exception as e:
                print(f"[Alert] Callback error: {e}")

    def check_overdue_breaks(self) -> List[Alert]:
        """Check for overdue breaks and generate alerts."""
        alerts = []
        overdue = get_overdue_sessions()

        for session in overdue:
            # Determine severity
            over_mins = session['over_limit_minutes']
            if over_mins >= 15:
                severity = 'critical'
            elif over_mins >= 5:
                severity = 'warning'
            else:
                continue  # Skip minor overages

            # Create alert message
            message = (
                f"{session['full_name']} is {over_mins:.0f} minutes over "
                f"the {session['time_limit_minutes']} min limit for {session['break_type_name']}"
            )

            alert = Alert(
                id=None,
                user_id=session['user_id'],
                full_name=session['full_name'],
                break_type=session['break_type_name'],
                alert_type='overdue',
                duration_minutes=session['duration_minutes'],
                over_limit_minutes=over_mins,
                message=message,
                timestamp=datetime.now().isoformat(),
                severity=severity
            )
            alerts.append(alert)

        return alerts

    def get_missing_clockbacks(self, for_date: str = None) -> List[Alert]:
        """Check for missing clock-back entries."""
        if for_date is None:
            for_date = datetime.now().strftime('%Y-%m-%d')

        alerts = []
        with get_connection() as conn:
            cursor = conn.execute("""
                SELECT
                    u.id as user_id,
                    u.full_name,
                    bt.display_name as break_type,
                    COUNT(CASE WHEN bl.action = 'OUT' THEN 1 END) as outs,
                    COUNT(CASE WHEN bl.action = 'BACK' THEN 1 END) as backs
                FROM break_logs bl
                JOIN users u ON bl.user_id = u.id
                JOIN break_types bt ON bl.break_type_id = bt.id
                WHERE bl.log_date = ?
                GROUP BY bl.user_id, bl.break_type_id
                HAVING outs > backs
            """, (for_date,))

            for row in cursor.fetchall():
                missing = row['outs'] - row['backs']
                message = (
                    f"{row['full_name']} has {missing} missing clock-back(s) "
                    f"for {row['break_type']}"
                )

                alert = Alert(
                    id=None,
                    user_id=row['user_id'],
                    full_name=row['full_name'],
                    break_type=row['break_type'],
                    alert_type='missing_back',
                    duration_minutes=0,
                    over_limit_minutes=0,
                    message=message,
                    timestamp=datetime.now().isoformat(),
                    severity='warning'
                )
                alerts.append(alert)

        return alerts

    async def check_and_alert(self) -> List[Alert]:
        """Run all checks and return new alerts."""
        new_alerts = []

        # Check overdue breaks
        overdue_alerts = self.check_overdue_breaks()
        for alert in overdue_alerts:
            new_alerts.append(alert)
            await self.notify_callbacks(alert)

        # Update recent alerts
        self.recent_alerts = new_alerts + self.recent_alerts[:50]

        return new_alerts

    async def start_monitoring(self, interval: int = 60):
        """Start continuous monitoring loop."""
        print(f"[Alert] Starting monitoring (every {interval}s)")
        while True:
            try:
                alerts = await self.check_and_alert()
                if alerts:
                    print(f"[Alert] Generated {len(alerts)} alerts")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Alert] Monitoring error: {e}")
            await asyncio.sleep(interval)

    def get_recent_alerts(self, limit: int = 20) -> List[Dict]:
        """Get recent alerts."""
        return [asdict(a) for a in self.recent_alerts[:limit]]

    def get_alert_summary(self) -> Dict:
        """Get summary of current alert status."""
        overdue = self.check_overdue_breaks()
        critical = sum(1 for a in overdue if a.severity == 'critical')
        warning = sum(1 for a in overdue if a.severity == 'warning')

        return {
            "total_active": len(overdue),
            "critical": critical,
            "warning": warning,
            "status": "critical" if critical > 0 else "warning" if warning > 0 else "ok"
        }


# Global alert manager
alert_manager = AlertManager()


# API endpoints for alerts
def get_alert_endpoints():
    """Return alert-related API endpoints."""
    from fastapi import APIRouter

    router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

    @router.get("")
    async def get_alerts(limit: int = 20):
        """Get recent alerts."""
        return {
            "alerts": alert_manager.get_recent_alerts(limit),
            "summary": alert_manager.get_alert_summary()
        }

    @router.get("/summary")
    async def get_alert_summary():
        """Get alert summary."""
        return alert_manager.get_alert_summary()

    @router.get("/overdue")
    async def get_overdue_alerts():
        """Get current overdue break alerts."""
        alerts = alert_manager.check_overdue_breaks()
        return {
            "count": len(alerts),
            "alerts": [asdict(a) for a in alerts]
        }

    @router.get("/missing")
    async def get_missing_clockback_alerts(date: str = None):
        """Get missing clock-back alerts."""
        alerts = alert_manager.get_missing_clockbacks(date)
        return {
            "count": len(alerts),
            "alerts": [asdict(a) for a in alerts]
        }

    return router
