"""HTTP wrapper around the Voyager client.

The server holds no LinkedIn credentials of its own. Every request carries the
caller's cookies, so there is nothing here to expire, rotate, or keep secret,
and nothing is ever written to disk. See ADR 0007.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from linkedin import LinkedInError, Voyager

# One Voyager per cookie pair, reused across requests. Reuse is not an
# optimisation: LinkedIn rotates li_at mid-session and hands the replacement
# back on a redirect, so a client built per request would drop it (ADR 0003).
_clients: dict[tuple[str, str], Voyager] = {}
MAX_CLIENTS = 32


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    for client in _clients.values():
        await client.aclose()
    _clients.clear()


app = FastAPI(
    title="LinkedIn Profile API",
    description=(
        "Give it a LinkedIn profile URL and your own session cookies, "
        "get structured JSON back."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


class ProfileRequest(BaseModel):
    url: str = Field(min_length=1, examples=["https://www.linkedin.com/in/name/"])
    # Both cookies come from the caller's own logged-in browser. The server
    # neither stores them nor has any of its own.
    li_at: str = Field(min_length=1)
    jsessionid: str = Field(min_length=1)


async def _client(body: ProfileRequest) -> Voyager:
    key = (body.li_at, body.jsessionid)
    if key not in _clients:
        # ponytail: plain FIFO evict, no TTL. A rotation makes a new key and
        # strands the old client; the cap is what eventually clears it. Swap
        # for an LRU with an idle timeout if that churn ever matters.
        if len(_clients) >= MAX_CLIENTS:
            await _clients.pop(next(iter(_clients))).aclose()
        _clients[key] = Voyager(body.li_at, body.jsessionid)
    return _clients[key]


@app.exception_handler(LinkedInError)
async def _linkedin_error(_request, exc: LinkedInError):
    return JSONResponse(status_code=exc.status, content={"error": str(exc)})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/profile")
async def profile(body: ProfileRequest):
    client = await _client(body)
    result = await client.fetch_profile(body.url)
    # LinkedIn may have rotated the session while we worked. Hand the current
    # cookies back: the pair the caller sent may already be superseded, and the
    # server keeps no copy for them to fall back on.
    result["session"] = client.cookies
    return result


@app.get("/")
async def root():
    return {
        "usage": "POST /profile with {url, li_at, jsessionid}",
        "docs": "/docs",
    }
