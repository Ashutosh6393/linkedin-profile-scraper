# 1. Reverse engineer the Voyager API instead of driving a browser

Date: 2026-08-30

## Status

Accepted.

## Context

The brief asks for a hosted API that takes a LinkedIn profile URL and returns
the profile as structured JSON. A follow-up clarification from the reviewers
made the constraint explicit:

> we are looking for a purely reverse-engineered solution that directly hits
> LinkedIn endpoints and does not use a browser.

That rules out Playwright, Puppeteer, Selenium, and any headless-Chrome
service. It also rules out the linked PhantomBuster automation as an
implementation model, since PhantomBuster drives a real browser session. The
PhantomBuster page is useful only as a reference for *which fields* the output
should carry.

The remaining options were:

1. Fetch the profile HTML with an HTTP client and parse the markup.
2. Call LinkedIn's own private JSON API directly.

Option 1 looked plausible because LinkedIn now server-renders profile pages.
Inspecting a live profile ruled it out: the rendered page carries no embedded
JSON payload. There are zero `<script type="application/json">` blocks and
zero `<code>` data islands. Parsing would mean scraping rendered DOM, which
breaks on any cosmetic redesign.

Option 2 exists because LinkedIn's web app is backed by a private JSON API at
`https://www.linkedin.com/voyager/api`. It is undocumented and unsupported,
but it is the same API their own frontend consumes, so it exposes everything
the profile page can show.

## Decision

Call Voyager directly over plain HTTP, authenticating with a real logged-in
session cookie supplied through environment variables.

Authentication is two cookies and a few headers:

| What | Value |
| --- | --- |
| `li_at` cookie | the login session |
| `JSESSIONID` cookie | session id |
| `csrf-token` header | the `JSESSIONID` value with quotes stripped |
| `x-restli-protocol-version` header | `2.0.0`, required or requests 400 |
| `accept` header | `application/vnd.linkedin.normalized+json+2.1` |

The `accept` header matters more than it looks. It makes Voyager reply in
**normalized** form: a flat `included` array where every object carries a
`$type` discriminator. That is far easier and more stable to parse than the
nested default representation.

## Consequences

- No browser binary, so the service is small, fast, and cheap to host. A
  profile lookup takes a few seconds, not tens of seconds.
- This violates LinkedIn's Terms of Service. The account whose cookie is used
  can be restricted or banned. A throwaway account is mandatory. This is
  stated in the README rather than buried.
- The API is unofficial and carries no stability promise. It can change
  without notice, and during this project we found one endpoint that already
  had. See ADR 0002.
- Output is limited to what the authenticated account is allowed to see.
  Out-of-network profiles may return partial data.
