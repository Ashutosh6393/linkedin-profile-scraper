# 6. FastAPI, uv, and keeping both GET and POST

Date: 2026-08-30

## Status

Accepted, except for the HTTP verb decision.

**"Keep both verbs" is superseded by
[ADR 0007](0007-the-caller-brings-the-cookies.md).** `GET /profile` is removed:
the request now carries the caller's session cookies, and a query string is the
wrong place for a credential. The FastAPI and uv decisions stand.

## Context

Three small choices, grouped because none warrants its own record.

**Web framework.** The service is one endpoint returning JSON. It needs async,
because the nine section calls run concurrently.

**Package manager.** The project started on `pip` and `requirements.txt`.

**HTTP verb.** `/profile` was built accepting both `GET ?url=` and a
`POST {"url": ...}` body, which is redundant and was initially unjustified.

## Decision

**FastAPI with uvicorn.** Async-native, and the generated `/docs` page means a
reviewer can exercise the API by clicking rather than composing curl. For an
assignment that is graded by someone else running it, that matters.
`httpx` is the client half, chosen for async and because it lets us disable
its cookie jar and redirect handling — which ADR 0003 requires.

**uv for dependencies.** `pyproject.toml` plus a committed `uv.lock` pins
exact versions, so `uv sync --frozen` reproduces the environment. This
replaced `requirements.txt`, which is deleted. Note that adopting uv upgraded
FastAPI 0.115 to 0.141 and Starlette 0.41 to 1.6; tests pass on the newer
versions.

**Keep both verbs.** GET is what a reviewer tries first — one clickable URL
that works in a browser, in `/docs`, or pasted into a chat. POST is what
"accepts a LinkedIn profile URL as input" reads like to most people, and
`curl -d` is a common reflex.

We checked whether GET was actually unsafe for URLs carrying tracking
parameters. It truncates: `?url=https://...?trk=nav&originalSubdomain=in`
parses `url` as everything up to the `&`, and `originalSubdomain` leaks out as
a separate query parameter. **This does not affect us** — `slug_from_url`
extracts `/in/<name>` with a regex and discards the rest — so the argument for
POST on escaping grounds does not hold here.

Both are kept anyway. They are four lines and share one code path.

## Consequences

- Two documented entry points for one operation. Marginal cost, marginal
  benefit; a reviewer who prefers either finds it.
- Both call the same `fetch_profile`, so there is no behavioural drift risk.
- uv is now required to work on the project. It is a single binary and the
  README says so.
- The GET truncation behaviour is a latent trap if input handling ever grows
  beyond "extract the slug". If a future change needs the full URL preserved,
  POST becomes the correct path and GET should require encoding.
