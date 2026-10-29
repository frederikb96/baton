"""Request body cap for the API routes."""

from __future__ import annotations

import contextlib

from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_BODY_BYTES = 16 * 1024
LIMITED_PREFIXES = ("/api/ui/", "/api/watch/")
TOO_LARGE = b'{"detail":"Request body too large."}'


class BodyTooLarge(Exception):
    """The body outgrew the cap while it was being read."""


class BodyLimitMiddleware:
    """Answer 413 to API requests whose body exceeds the cap, without reading the rest.

    A declared ``Content-Length`` over the cap is refused before any byte is read; a body
    without one is cut off as soon as the cap is crossed.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(LIMITED_PREFIXES):
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(send)
            return

        received = 0
        refused = False
        started = False

        async def counting_receive() -> Message:
            nonlocal received, refused
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    refused = True
                    raise BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if not refused:
                started = started or message["type"] == "http.response.start"
                await send(message)

        # The framework may turn the aborted read into its own error response (suppressed
        # above) or let the exception through; either way the client gets the 413.
        with contextlib.suppress(BodyTooLarge):
            await self.app(scope, counting_receive, guarded_send)
        if refused and not started:
            await self._refuse(send)

    @staticmethod
    async def _refuse(send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(TOO_LARGE)).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": TOO_LARGE})
