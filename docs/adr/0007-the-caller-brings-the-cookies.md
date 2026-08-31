# 7. The caller brings the cookies; the server stores nothing

Date: 2026-08-31

## Status

Accepted. Supersedes point 5 of [ADR 0003](0003-manage-cookies-by-hand-and-persist-the-session.md)
(persisting the jar to `.session.json`) and the "keep both verbs" decision in
[ADR 0006](0006-fastapi-uv-and-both-http-verbs.md).

## Context

Until now the service owned one LinkedIn session. Two cookies were pasted into
`.env`, the client rotated them as it worked, and the rotated pair was written
to `.session.json` so a restart did not lose the session.

That works on a laptop. It does not survive being deployed.

**The session file has nowhere to live.** Render, Railway, and Fly give a
container an ephemeral filesystem. `.session.json` is wiped on every restart
and every deploy. The process then comes back up, reads the stale value out of
the environment, and dies on the first request — ADR 0003's Failure 3, except
now it fires on every deploy rather than twice during development. Fixing that
means attaching a volume, which is real infrastructure for one small file.

**The credential is single-tenant.** One deployment could only ever act as one
LinkedIn account, and that account's ban risk (ADR 0004) is carried by whoever
runs the server rather than whoever makes the requests.

**Nobody can rotate it but the operator.** When `li_at` finally expires,
somebody has to open a dashboard and redeploy.

The service is meant to be an API other people call. All three problems come
from the same root: the server holding a credential it has no good way to
store, refresh, or attribute.

## Decision

**The server holds no LinkedIn credentials at all.**

1. `POST /profile` requires `url`, `li_at`, and `jsessionid`. All three are
   required; a missing or empty one is a 422 before any network call.
2. `GET /profile` is removed. Cookies in a query string end up in access logs,
   proxy logs, and browser history. A body is the only way in. This reverses
   ADR 0006, whose case for GET was reviewer convenience — that was the right
   trade when the cookie was the operator's, and it is the wrong one now that
   it belongs to the caller.
3. `.env`, `python-dotenv`, `.session.json`, `LINKEDIN_SESSION_FILE`, and the
   whole load/save path are deleted. There is no configuration.
4. **One `Voyager` per cookie pair is cached in memory** for the process's
   lifetime. This is not an optimisation. ADR 0003's Failure 1 still applies:
   a client built per request drops the rotated cookie and the session works
   exactly once. The cache is capped at 32 with a FIFO eviction that closes the
   client it drops.
5. **The current cookies are returned in every response** as `session`. A
   rotation retires the pair the caller sent, and the server keeps no copy, so
   returning them is the only way the caller can stay in step.

Cookie values are validated on the way in: a `;`, a `\r`, or a `\n` is
rejected with a 400. They are interpolated straight into a `Cookie` header, and
before this change they came from a trusted `.env` rather than the network.

## Consequences

- Deployment needs no secrets, no environment variables, and no volume. A
  restart or redeploy costs nothing, because there is nothing to lose.
- Ban risk moves to the caller, where it belongs. One deployment serves any
  number of accounts.
- **Callers must store the `session` field and send it back.** A caller that
  keeps replaying its original cookies will work until the process restarts,
  then get a 502. This is documented in the README and is the main cost of
  the decision.
- Live credentials now cross the network on every request. HTTPS is mandatory,
  not advisory.
- Cookies sit in memory for as long as a client is cached. They are never
  logged and never written to disk, but a memory dump would hold them. A
  shorter cache TTL is the lever if that ever matters.
- There is still no authentication and no per-caller rate limit. Anyone who
  can reach the service can spend their own cookie on it. Adding both is the
  obvious next step before the URL is public.
- Running several instances is safe, except that two concurrent requests from
  one caller can land on different instances and rotate the same session
  independently, superseding each other.
