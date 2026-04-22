"""ASGI middleware to host the app under a URL path prefix transparently.

The Replit path-based proxy forwards requests with the prefix intact (e.g.
`/app/login` arrives as `/app/login`). FastAPI's routes are declared at root
(`/login`, `/dashboard`, ...) and the Jinja templates use hardcoded
root-relative URLs. Rather than refactor every route and template, this
middleware:

  1. Strips the configured prefix from incoming request paths so existing
     routes match.
  2. Sets `root_path` in the ASGI scope so Starlette's `url_for` generates
     correctly prefixed URLs.
  3. Rewrites HTML response bodies to prepend the prefix to root-relative
     `href`, `action`, `src`, and `formaction` attributes.
  4. Rewrites `Location` headers on redirect responses so server-side
     redirects to e.g. `/dashboard` become `/app/dashboard`.

When the prefix is empty (e.g. local dev on a bare port), the middleware is a
no-op pass-through.
"""
from __future__ import annotations

import re
from typing import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PrefixMiddleware:
    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self.prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""
        # Pre-compile patterns when active.
        if self.prefix:
            p = re.escape(self.prefix.lstrip("/"))
            # Match href/action/src/formaction starting with a single '/'
            # but not protocol-relative (//) and not already prefixed.
            # "Already prefixed" means /app followed by a real boundary:
            # '/', '?', '#', or the closing quote — anything else (e.g.
            # /apple) is a different path that legitimately starts with
            # the same letters.
            self._attr_re = re.compile(
                rb'(\s(?:href|action|src|formaction)=")/(?!/)(?!'
                + p.encode()
                + rb'(?:/|\?|#|"))',
            )
            self._prefix_b = self.prefix.encode()
        else:
            self._attr_re = None
            self._prefix_b = b""

    def _location_already_prefixed(self, v: bytes) -> bool:
        """True if a Location header value already starts with our prefix at
        a real boundary (/, ?, #, or end-of-string)."""
        p = self._prefix_b
        if not v.startswith(p):
            return False
        if len(v) == len(p):
            return True
        return v[len(p):len(p) + 1] in (b"/", b"?", b"#")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.prefix or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        if not (path == self.prefix or path.startswith(self.prefix + "/")):
            # Outside the prefix: pass through unchanged.
            await self.app(scope, receive, send)
            return

        # Per Starlette convention, scope["path"] includes root_path; routes
        # use get_route_path() to obtain the path with root_path stripped.
        # So we keep `path` as-is and only set `root_path`.
        new_scope = dict(scope)
        new_scope["root_path"] = self.prefix

        prefix_b = self._prefix_b
        attr_re = self._attr_re
        state = {"is_html": False, "buffer": b"", "started": False}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # First pass: detect HTML so we know whether to drop content-length.
                for k, v in headers:
                    if k.lower() == b"content-type" and b"text/html" in v.lower():
                        state["is_html"] = True
                        break
                new_headers = []
                for k, v in headers:
                    lk = k.lower()
                    if (
                        lk == b"location"
                        and v.startswith(b"/")
                        and not v.startswith(b"//")
                        and not self._location_already_prefixed(v)
                    ):
                        v = prefix_b + v
                    if lk == b"content-length" and state["is_html"]:
                        # We will rewrite the body, so drop the precomputed length.
                        continue
                    new_headers.append((k, v))
                message = dict(message)
                message["headers"] = new_headers
                state["started"] = True
                await send(message)
                return

            if message["type"] == "http.response.body" and state["is_html"]:
                body = message.get("body", b"") or b""
                more = message.get("more_body", False)
                state["buffer"] += body
                if more:
                    return
                rewritten = attr_re.sub(rb"\1" + prefix_b + b"/", state["buffer"]) if attr_re else state["buffer"]
                await send({"type": "http.response.body", "body": rewritten, "more_body": False})
                return

            await send(message)

        await self.app(new_scope, receive, send_wrapper)
