# CLAUDE.md

Notes for anyone (human or agent) working on this repo.

## What this is

A hosted API that takes a LinkedIn profile URL and returns the profile as
JSON. It works by calling LinkedIn's private Voyager API directly over HTTP.

**No browser automation.** No Playwright, Puppeteer, Selenium, or headless
Chrome. That is a hard requirement from the brief, not a preference. If a
change would need a browser, it is the wrong change.

## Commands

```bash
uv sync                              # install from uv.lock
uv run python test_parse.py          # offline self-check, no cookies, no network
uv run uvicorn main:app --reload     # serve on :8000, docs at /docs
```

`uv` only. There is no `requirements.txt` and no `pip install`.

## Layout

| File | Holds |
| --- | --- |
| `linkedin.py` | Voyager client, cookie/session handling, all parsing |
| `main.py` | FastAPI routes, lifespan, error mapping |
| `test_parse.py` | the self-check |
| `docs/adr/` | why things are the way they are |

## Before you touch anything

**Read `docs/adr/`.** Several parts of this code look wrong and are not. The
cookie handling in particular (ADR 0003) deliberately bypasses `httpx`'s
cookie jar and redirect following, because the library's correct behaviour is
what breaks against LinkedIn.

## Rules that matter

**The server holds no credentials, and it stays that way.** Cookies arrive in
the request body and are returned in the `session` field. There is no `.env`,
no `.session.json`, and no config. Do not add a fallback that reads cookies
from the environment, and never write a caller's cookies to disk or a log —
they belong to someone else. See ADR 0007.

Since cookies now arrive over the network, they are untrusted input. The
validation in `Voyager.__init__` stops `;` and line breaks from reaching the
`Cookie` header. Keep it.

**Do not hammer LinkedIn.** One profile lookup is ten requests. The account
behind the cookie gets banned, not the code. When testing:

- One request is a test. A loop is a scrape.
- Never put a profile fetch in a retry loop or a benchmark.
- `test_parse.py` covers the parsing logic offline. Use it. It needs no
  cookies and touches no network.
- If something looks broken, read `docs/adr/0003` before firing more requests
  at it. Most "it's rate limiting me" symptoms are the session-rotation bug.

**Throttle constants are load-bearing.** `MAX_CONCURRENCY`,
`DELAY_BETWEEN_CALLS`, `MAX_REDIRECTS` in `linkedin.py`. Raising them raises
the ban risk. See ADR 0004.

## Gotchas that will cost you an afternoon

- **`profileView` is 410 Gone.** Every tutorial and most open-source LinkedIn
  libraries still use it. They are broken. Use the dash finders.
- **A 302 to the same URL is normal.** It is a cookie rotation, not an error.
- **First request works, everything after 403s** means a rotated cookie got
  dropped. That is ADR 0003, not a rate limit.
- **`count=100` is required** on section finders, or you silently get the
  first 20 rows only.
- **`csrf-token` must equal the current `JSESSIONID`.** If one rotates and the
  other does not follow, every request bounces.
- **Voyager `queryId` hashes are per frontend build.** Do not pin one. That is
  why we use REST finders, not GraphQL.

## Changing the response

Parsing lives in `parse_profile` and the `_experience` / `_education` / etc.
mappers. It is a pure function — no network, no client. Keep it that way; it
is what makes the tests runnable without cookies.

Adding a field is one line in the relevant mapper plus an assertion in
`test_parse.py`.

## Style

Plain, boring Python. Comments explain *why*, not *what* — most of the
non-obvious code here exists to work around LinkedIn behaviour, and that
reason is the useful part. Match what is already in the file.
