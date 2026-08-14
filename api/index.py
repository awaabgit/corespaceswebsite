"""
Vercel entry point.

Vercel's Python runtime looks for a module in api/ that exports an ASGI app
called `app`, and hands every request to it. All the real code stays in app/ —
this file only adapts it, so the same codebase still runs unchanged under plain
uvicorn locally (`./run.sh`) and on any normal host.

Requests for /static/* never reach here: those files live in public/ and are
served straight off Vercel's CDN, which is why the 2.7MB hero video doesn't
cost a function invocation.

Why the prefix stripping below:
    vercel.json rewrites every request to /api/index/<original path> so the
    path survives the rewrite. Without the "/$1" on the end Vercel replaces the
    path entirely, FastAPI receives "/api/index", matches no route, and every
    page returns {"detail":"Not Found"}. We put the path back before FastAPI
    sees it.
"""
import sys
from pathlib import Path

# Vercel executes this file with api/ as the working directory, so the project
# root (which holds the `app` package) isn't importable by default.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app as _app  # noqa: E402

_PREFIX = "/api/index"


class _StripMountPrefix:
    """
    ASGI middleware that removes Vercel's routing prefix from the request path.

    A no-op anywhere the prefix isn't present, so running under uvicorn locally
    behaves exactly as before.
    """

    def __init__(self, asgi_app, prefix: str):
        self.app = asgi_app
        self.prefix = prefix

    async def __call__(self, scope, receive, send):
        if scope.get("type") in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                stripped = path[len(self.prefix):] or "/"
                scope = dict(scope)
                scope["path"] = stripped
                # Starlette prefers raw_path when it is set, so keep it in step.
                if scope.get("raw_path"):
                    scope["raw_path"] = stripped.encode("utf-8")
        await self.app(scope, receive, send)


app = _StripMountPrefix(_app, _PREFIX)
