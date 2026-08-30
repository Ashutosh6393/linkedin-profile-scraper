# 4. Throttle requests to limit account risk

Date: 2026-08-30

## Status

Accepted.

## Context

ADR 0002 leaves us at ten HTTP requests per profile lookup. The first
implementation fired the nine section calls with a bare `asyncio.gather`, so
they left as one simultaneous burst.

LinkedIn's rate limits are real and unpublished. The consequence of crossing
them is not a clean `429` — it is the account getting challenged or
restricted. The cost of being wrong falls on a person's account, not on a
retryable request.

A second, self-inflicted source of load turned up during debugging. httpx's
default `max_redirects` is 20, so each attempt against a dead session fired
twenty requests before raising. Two failed attempts were forty wasted requests
that all looked like scraping.

## Decision

Three limits, all named constants at the top of `linkedin.py` so they are easy
to find and tune:

```python
MAX_CONCURRENCY     = 3     # in flight at once, via asyncio.Semaphore
DELAY_BETWEEN_CALLS = 0.4   # seconds, inside the semaphore
MAX_REDIRECTS       = 4     # per request, manual redirect loop
```

Three in flight with a short gap reads like a person browsing rather than a
burst. `MAX_REDIRECTS = 4` means a dead session costs four requests to
discover, not twenty.

## Consequences

- A profile lookup takes roughly 3-4 seconds instead of the theoretical
  minimum. That is an acceptable trade for a service whose failure mode is
  somebody's account getting banned.
- This is a courtesy, not a guarantee. It protects against accidental bursts,
  not against sustained volume. Anything running this at scale needs a real
  queue in front of it, plus caching so repeated lookups do not re-hit
  LinkedIn. Neither is built. Both are listed in the README limitations.
- The constants are deliberately conservative. If throughput ever matters more
  than caution, they are the first thing to raise — but the account risk goes
  up with them.
