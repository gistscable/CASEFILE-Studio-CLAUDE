"""Serve the demo gallery (index.html + MP4s, with HTTP Range so video seeking works).
From casefile-studio/:  .venv/bin/python qa/cinegfx-demos/serve.py  -> http://0.0.0.0:8001/"""
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.staticfiles import StaticFiles

app = Starlette()
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent, html=True))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="warning")
