"""
Vercel entry point.

Vercel's Python runtime looks for a module in api/ that exports an ASGI app
called `app`, and hands every request to it. All the real code stays in app/ —
this file only re-exports it, so the same codebase still runs unchanged under
plain uvicorn locally (`./run.sh`) and on any normal host.

Requests for /static/* never reach here: those files live in public/ and are
served straight off Vercel's CDN, which is why the 2.7MB hero video doesn't
cost a function invocation.
"""
import sys
from pathlib import Path

# Vercel executes this file with api/ as the working directory, so the project
# root (which holds the `app` package) isn't importable by default.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402,F401  — re-exported for the runtime
