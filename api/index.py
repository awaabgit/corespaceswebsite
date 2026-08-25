"""
Vercel entry point.

Vercel's Python runtime looks in api/ for a module exporting an ASGI app named
`app`. All the real code stays in app/ — this file only adapts it, so the same
codebase still runs unchanged under plain uvicorn locally (`./run.sh`) and on
any normal host.

Requests for /static/* never reach here: those files live in public/ and are
served straight off Vercel's CDN, which is why the 2.7MB hero video doesn't
cost a function invocation.

Two things this file has to get right, both learned the hard way:

1. `app` must BE the FastAPI instance. Wrapping it in a custom class stopped
   Vercel recognising it as an ASGI app, so no function was created at all and
   every URL — /api/index included — returned a bare platform 404. The path
   fix below is therefore installed as middleware ON the app, not around it.

2. The request path has to be restored. A rewrite to a bare "/api/index"
   replaces the path, so FastAPI saw "/api/index" for every request, matched no
   route, and answered {"detail":"Not Found"} on every page. vercel.json now
   passes the original path along as __vpath and the middleware puts it back.
"""
import os
import sys
import urllib.parse
from pathlib import Path

# Vercel executes this file with api/ as the working directory, so the project
# root (which holds the `app` package) isn't importable by default.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402  — re-exported for the runtime

_PREFIX = "/api/index"
_PATH_PARAM = "__vpath"
_COMMIT = (os.getenv("VERCEL_GIT_COMMIT_SHA") or "local")[:8]


class VercelPathFix:
    """
    Put the real request path back before FastAPI routes the request.

    Handles every shape the platform might hand us, and is a no-op when none
    apply — so uvicorn locally and any other host are unaffected:

      * "?__vpath=listings"  -> "/listings"   (what vercel.json sends)
      * "/api/index/listings" -> "/listings"  (if the path is passed through)
      * "/listings"           -> unchanged    (local dev, other hosts)
    """

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        scope = dict(scope)
        path = scope.get("path", "")
        original = path
        original_query = scope.get("query_string", b"").decode("latin-1")

        # the original path, handed over as a query parameter
        query = scope.get("query_string", b"").decode("latin-1")
        carried, kept = None, []
        for key, value in urllib.parse.parse_qsl(query, keep_blank_values=True):
            if key == _PATH_PARAM and carried is None:
                carried = value
            else:
                kept.append((key, value))

        if carried is not None:
            path = "/" + carried.lstrip("/")
            # drop our own parameter so the page's real filters are untouched
            scope["query_string"] = urllib.parse.urlencode(kept).encode("latin-1")
        elif path == _PREFIX or path.startswith(_PREFIX + "/"):
            path = path[len(_PREFIX):] or "/"

        scope["path"] = path
        if scope.get("raw_path"):
            # Starlette prefers raw_path when it is set, so keep it in step
            scope["raw_path"] = path.encode("utf-8")

        # Report what the platform handed us on every response, 404s included.
        # Routing on a serverless host can only really be diagnosed from
        # outside, and these three headers make it a single curl instead of a
        # guess-and-redeploy cycle. Headers only -- nothing a visitor sees.
        async def send_with_marks(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [
                    (b"x-cs-commit", _COMMIT.encode("latin-1")),
                    (b"x-cs-path-in", original.encode("latin-1")[:200]),
                    (b"x-cs-path-out", path.encode("latin-1")[:200]),
                    (b"x-cs-query-in", original_query.encode("latin-1")[:200]),
                ]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_marks)


# Added to the app rather than wrapped around it, so `app` stays a FastAPI
# instance and Vercel still detects it. add_middleware puts this outermost,
# so the path is corrected before routing or any other middleware runs.
app.add_middleware(VercelPathFix)
