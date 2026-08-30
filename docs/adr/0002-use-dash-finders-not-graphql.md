# 2. Use the dash REST finders, not profileView and not GraphQL

Date: 2026-08-30

## Status

Accepted.

## Context

Voyager exposes more than one way to read a profile. We probed three against a
live logged-in session.

**`/identity/profiles/{slug}/profileView`** returns **410 Gone**.

This is the endpoint nearly every open-source LinkedIn scraper library is
built on, because it used to return the whole profile — positions, educations,
skills, certifications — in a single call. It is retired. Any tutorial or
library still recommending it is broken, which is worth knowing before
spending a day debugging someone else's wrapper.

**`/voyager/api/graphql?variables=(...)&queryId=<name>.<32-hex-hash>`** works,
but the `queryId` hash is generated per frontend build. You cannot invent it;
you have to harvest it from live traffic and pin it in code.

We tried to harvest it and could not, for a reason specific to how LinkedIn
works now. Every profile route is server-rendered. Loading a profile, loading
`/details/experience/`, and scrolling produced no profile GraphQL call at all
— the only GraphQL traffic on a profile page was `voyagerDashMySettings` and
messaging. Scanning all 21 eagerly-loaded JS bundles for a `name.<32 hex>`
pattern returned zero matches; the query IDs live in lazily-loaded route
chunks that a server-rendered page never requests.

Even if harvested, a pinned hash is a liability: it silently dies on the next
frontend deploy.

**`/identity/dash/{collection}?q=viewee&profileUrn=<urn>`** works, needs no
hash, and returned a 200 for every section we tried.

## Decision

Fetch the core profile, then fan out to the dash finders.

```
GET /identity/dash/profiles?q=memberIdentity&memberIdentity=<slug>
```

That returns the core object — names, headline, `summary`, images — and, more
importantly, the `entityUrn`. The URN is the key for everything else. Then
nine section finders, each `?q=viewee&profileUrn=<urn>&count=100`:

```
profilePositions  profileEducations  profileSkills
profileCertifications  profileLanguages  profileProjects
profileCourses  profileHonors  profileVolunteerExperiences
```

`count=100` is not optional. Without it the finders return only the first 20
rows; a real profile silently lost half its skills (39 came back as 20).

## Consequences

- No build-specific hash anywhere in the codebase, so a LinkedIn frontend
  deploy does not break us.
- Ten HTTP requests per profile instead of one. That is the cost of
  `profileView` being retired. The requests run concurrently, so wall-clock
  time stays around 3-4 seconds, but it does raise the rate-limit footprint.
  See ADR 0004.
- Sections are independent, which enables per-section failure isolation.
  See ADR 0005.
- Some fields still need URN resolution we do not do. `location` comes back as
  a country code plus a `geoUrn`; the human-readable "Lucknow, Uttar Pradesh,
  India" is resolved server-side for the rendered page. `/identity/dash/geos/<urn>`
  returns 404 and the GraphQL geo query needs a build hash, so the geo URN is
  passed through as-is. Per-position `location` strings do come through.
