#!/usr/bin/env python3
"""
Development server runner for Kolya BR Proxy.
"""

import os
import sys
from pathlib import Path

# Add backend directory to Python path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Set environment variables for development
os.environ.setdefault("KBR_DEBUG", "true")
os.environ.setdefault("KBR_PORT", "8000")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
