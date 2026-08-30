# 5. Own the response schema, and isolate section failures

Date: 2026-08-30

## Status

Accepted.

## Context

The brief says "the response schema is yours to design" and asks for name,
headline, location, about, experience, education, skills, certifications,
languages, and profile images.

Voyager's normalized payloads are not a usable public shape. They are flat
`included` arrays of objects keyed by `$type` and cross-referenced by
`entityUrn`, carrying LinkedIn-internal fields like `multiLocaleTitle`,
`versionTag`, `trackingId`, and `displayBadges`. Dates arrive as
`{"year": 2025, "month": 10}`. Images are not URLs at all: Voyager returns a
`rootUrl` plus a list of size `artifacts`, and the real URL is
`rootUrl + fileIdentifyingUrlPathSegment`.

Separately, we are consuming nine independent undocumented endpoints. Any one
of them can be changed or retired without notice — `profileView` already was.
If one finder starts failing, returning a 502 for the entire profile would
throw away nine sections of good data.

## Decision

**Own the schema.** Map Voyager's shapes to a flat, stable, camelCase
structure. Dates normalise to `"2025-10"` / `"2021"` strings. Images resolve
to a real `url` plus a `sizes` map, defaulting to the largest artifact.
Experience gains a derived `current` boolean, since "no end date" meaning
"still there" is not obvious to a consumer.

Parsing is a **pure function**, `parse_profile(core, sections)`. No network, no
client, no cookies. That is what makes the logic testable offline against
captured payloads.

**Isolate section failures.** The nine finders run under
`asyncio.gather(..., return_exceptions=True)`. A section that raises becomes
`[]` in the response; the rest of the profile still returns.

## Consequences

- The response is stable even though the upstream is not. A LinkedIn field
  rename affects one mapper function, not every consumer.
- `test_parse.py` runs with no cookies and no network, so the parsing logic
  stays covered even when the session is dead.
- A missing section and an empty section are indistinguishable — both are
  `[]`. A caller cannot tell "this person has no certifications" from "the
  certifications finder broke". Adding a per-section status map would fix it;
  not worth the response-shape noise yet.
- We drop fields we do not map. That is intentional; the raw payloads carry a
  lot of LinkedIn-internal noise. Adding a field means adding one line to the
  relevant mapper.
