# 3. Manage cookies by hand and persist the rotated session

Date: 2026-08-30

## Status

Accepted. This is the least obvious decision in the project and the one that
cost the most debugging, so it is written up in full.

## Context

LinkedIn does not treat `li_at` as a static bearer token. It **rotates the
session cookie underneath you**, handing the replacement back in a
`Set-Cookie` header, often on a `302` that points at the exact URL you just
requested.

That self-redirect is normal traffic, not an error. But it means a naive
client hits three separate failure modes, and all three look like a rate limit
or a ban when they are neither.

### Failure 1: a client built per request

The first implementation created a fresh `httpx.AsyncClient` inside
`fetch_profile`. Sequence observed against the live API:

```
request 1  -> 200 OK + Set-Cookie: li_at=<new>    (discarded on client close)
request 2  -> old li_at is now superseded -> 403
```

The service worked exactly once, then failed permanently. Restarting made it
work once more. That reads like throttling and is not.

### Failure 2: httpx's cookie jar is domain-aware

Sharing one long-lived client fixed the first profile fetch, then the *second*
profile died in a redirect loop. Cause: we seeded `li_at` on `.linkedin.com`,
LinkedIn set the rotated `li_at` on a different domain, and the jar happily
held **both**. Every subsequent request sent two `li_at` values, LinkedIn read
the stale one, and bounced us. `max_redirects` then turned each attempt into
twenty wasted requests.

A diagnostic isolated it. With redirects capped at 1:

```
dict jar                    -> TooManyRedirects
explicit .linkedin.com jar  -> TooManyRedirects
raw Cookie header           -> 403   (credentials genuinely stale by then)
```

The raw header behaved differently from both jar variants, which is what
pointed at duplicate cookies rather than bad credentials.

### Failure 3: restarts lose the rotation

Even with rotation handled in memory, a process restart falls back to whatever
was pasted into `.env`. LinkedIn may have superseded that value hours ago, so
the service comes up already dead and a human has to re-copy cookies from the
browser. During development this happened twice.

## Decision

Take cookie handling away from the HTTP library entirely.

1. **A plain dict, keyed by cookie name.** One name maps to one value, so a
   stale duplicate cannot exist. `httpx.AsyncClient` is constructed with
   `follow_redirects=False` and no jar.
2. **Redirects are followed by hand**, up to `MAX_REDIRECTS = 4`. Each hop
   rebuilds the `Cookie` header from the current dict, so a rotation mid-chain
   is picked up immediately. Exhausting the budget raises a clear "the session
   is dead, copy fresh cookies" error rather than `TooManyRedirects`.
3. **Every response is absorbed.** `Set-Cookie` values are merged into the
   dict. An empty value is a deletion and is ignored. When `JSESSIONID`
   changes, the `csrf-token` header is re-synced in the same step, because the
   two must always match.
4. **One client for the whole app lifetime**, built in the FastAPI lifespan
   hook, so the session survives between requests.
5. **The jar is written to `.session.json` on every change**, through a temp
   file and an atomic replace. On startup the saved file **outranks `.env`**:
   the value we last received beats one typed in by hand days ago.

Mutation is guarded by an `asyncio.Lock`, since nine section requests run
concurrently and any of them can carry a rotation.

## Consequences

- Cookies are pasted **once**. The service maintains its own session across
  restarts.
- A dead session now fails in four requests with an actionable message,
  instead of twenty requests and `TooManyRedirects`.
- `.session.json` is plaintext credentials on disk. It is gitignored, but on a
  shared host it should be a secrets store instead. Flagged in the README.
- We reimplement a small slice of cookie handling that a library would
  normally own. That is deliberate: the library's correct, domain-aware
  behaviour is precisely what breaks against LinkedIn here.
- Rotated values are never written back to `.env`. `.env` is the bootstrap
  seed; `.session.json` is the live state. Deleting the latter forces a fresh
  start.
