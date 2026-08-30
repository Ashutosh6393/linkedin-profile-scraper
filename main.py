"""HTTP wrapper around the Voyager client."""
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from linkedin import LinkedInError, Voyager

load_dotenv()

# One client for the whole app. It must be shared: LinkedIn rotates the li_at
# cookie mid-session and hands the replacement back on a redirect. A per-request
# client would drop it and the session would die after the first call.
_voyager: Voyager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _voyager
    li_at = os.getenv("LINKEDIN_LI_AT", "")
    jsessionid = os.getenv("LINKEDIN_JSESSIONID", "")
    _voyager = Voyager(li_at, jsessionid) if li_at and jsessionid else None
    yield
    if _voyager:
        await _voyager.aclose()


app = FastAPI(
    title="LinkedIn Profile API",
    description="Give it a LinkedIn profile URL, get structured JSON back.",
    version="1.0.0",
    lifespan=lifespan,
)


class ProfileRequest(BaseModel):
    url: str


def _client() -> Voyager:
    if _voyager is None:
        raise LinkedInError(
            "LINKEDIN_LI_AT and LINKEDIN_JSESSIONID are not set.", 500
        )
    return _voyager


@app.exception_handler(LinkedInError)
async def _linkedin_error(_request, exc: LinkedInError):
    return JSONResponse(status_code=exc.status, content={"error": str(exc)})


@app.get("/health")
async def health():
    return {"status": "ok", "credentialsConfigured": _voyager is not None}


@app.get("/profile")
async def profile_get(url: str):
    return await _client().fetch_profile(url)


@app.post("/profile")
async def profile_post(body: ProfileRequest):
    return await _client().fetch_profile(body.url)


@app.get("/")
async def root():
    return {
        "usage": "GET /profile?url=<linkedin profile url>  or  POST /profile",
        "docs": "/docs",
    }
