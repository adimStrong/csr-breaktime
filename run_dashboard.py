"""
CSR Breaktime Dashboard - Server Runner
Starts the dashboard API server with hot reload.
"""

import os
import sys
import webbrowser
from threading import Timer

# Setup environment
os.environ['BASE_DIR'] = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ['BASE_DIR'])

def open_browser():
    """Open dashboard in browser after server starts."""
    webbrowser.open('http://localhost:8000')

if __name__ == "__main__":
    import uvicorn

    print("=" * 50)
    print("CSR Breaktime Dashboard")
    print("=" * 50)
    print()
    print("Starting server...")
    print()
    print("  Dashboard:  http://localhost:8000")
    print("  API Docs:   http://localhost:8000/docs")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 50)

    # Open browser after 1.5 seconds
    Timer(1.5, open_browser).start()

    uvicorn.run(
        "dashboard.api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[os.environ['BASE_DIR']]
    )
