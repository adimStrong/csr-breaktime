"""
CSR Breaktime Dashboard - WebSocket Handler
Real-time updates for dashboard clients.
"""

import asyncio
import json
from datetime import datetime
from typing import Set
from dataclasses import asdict

from fastapi import WebSocket, WebSocketDisconnect

from dashboard.aggregations import (
    get_realtime_dashboard_metrics,
    get_active_breaks_list,
    get_overdue_breaks_list,
)


class ConnectionManager:
    """Manages WebSocket connections for real-time updates."""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()
        self._broadcast_task = None

    async def connect(self, websocket: WebSocket):
        """Accept new WebSocket connection."""
        await websocket.accept()
        self.active_connections.add(websocket)
        print(f"[WS] Client connected. Total: {len(self.active_connections)}")

        # Send initial data
        await self.send_personal(websocket, await self.get_realtime_data())

    def disconnect(self, websocket: WebSocket):
        """Remove disconnected client."""
        self.active_connections.discard(websocket)
        print(f"[WS] Client disconnected. Total: {len(self.active_connections)}")

    async def send_personal(self, websocket: WebSocket, data: dict):
        """Send data to a specific client."""
        try:
            await websocket.send_json(data)
        except Exception as e:
            print(f"[WS] Send error: {e}")
            self.disconnect(websocket)

    async def broadcast(self, data: dict):
        """Broadcast data to all connected clients."""
        if not self.active_connections:
            return

        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(data)
            except Exception:
                dead_connections.add(connection)

        # Clean up dead connections
        for conn in dead_connections:
            self.active_connections.discard(conn)

    async def get_realtime_data(self) -> dict:
        """Get current real-time data for broadcast."""
        metrics = get_realtime_dashboard_metrics()
        active = get_active_breaks_list()
        overdue = get_overdue_breaks_list()

        return {
            "type": "realtime_update",
            "timestamp": datetime.now().isoformat(),
            "data": {
                "metrics": metrics.to_dict(),
                "active_breaks": [asdict(b) for b in active],
                "overdue_breaks": [asdict(b) for b in overdue],
                "overdue_count": len(overdue)
            }
        }

    async def start_broadcast_loop(self, interval: int = 10):
        """Start periodic broadcast loop."""
        print(f"[WS] Starting broadcast loop (every {interval}s)")
        while True:
            try:
                if self.active_connections:
                    data = await self.get_realtime_data()
                    await self.broadcast(data)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[WS] Broadcast error: {e}")
                await asyncio.sleep(interval)


# Global connection manager
manager = ConnectionManager()


async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint handler."""
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            # Echo or handle commands
            if data == "ping":
                await manager.send_personal(websocket, {"type": "pong"})
            elif data == "refresh":
                await manager.send_personal(websocket, await manager.get_realtime_data())
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        print(f"[WS] Error: {e}")
        manager.disconnect(websocket)
