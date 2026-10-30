"""Run the API:  python -m api  (add --reload while developing).

Listens on 0.0.0.0 so a phone on the same network can reach it; PORT sets the port.
Run one process: sync jobs are tracked in memory (see api/sync_jobs.py).
"""

import os
import sys

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")),
                reload="--reload" in sys.argv)
