from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from packages.shared.config import settings


class BodyLimitMiddleware:
    """Count bytes before multipart parsing, including chunked requests."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        size = 0
        limit = (settings().max_upload_mb + 1) * 1024 * 1024

        async def bounded_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise HTTPException(413, "Upload exceeds configured size limit.")
            return message

        await self.app(scope, bounded_receive, send)
