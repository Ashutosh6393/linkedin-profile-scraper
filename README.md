# LinkedIn Profile API

Give it a LinkedIn profile URL, get the profile back as structured JSON.

No browser, no headless Chrome, no Selenium. It sends plain HTTP requests to
LinkedIn's own private JSON API and parses the response.

---

## Quick start

Dependencies are managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                         # builds .venv from pyproject.toml + uv.lock
cp .env.example .env            # then fill in the two cookie values
uv run uvicorn main:app --reload
```

`uv sync` installs the exact versions in `uv.lock`, so the environment is
reproducible. `uv run` uses the project environment without activating it.
No global installs, no `pip`.

Open http://127.0.0.1:8000/docs for the interactive docs.

### Getting the two cookie values

1. Log in to linkedin.com in Chrome.
2. Open DevTools → **Application** → **Cookies** → `https://www.linkedin.com`.
3. Copy `li_at` into `LINKEDIN_LI_AT`.
4. Copy `JSESSIONID` into `LINKEDIN_JSESSIONID`. Drop the surrounding quotes.

Use a throwaway LinkedIn account. See [Known limitations](#known-limitations).

You paste these **once**. LinkedIn rotates them as you use the API, and the
current values are kept in `.session.json` (gitignored) so a restart does not
lose the session. Delete that file if you ever want to force a fresh start
from `.env`.

---

## API

### `GET /profile?url=<linkedin profile url>`
### `POST /profile`

```json
{ "url": "https://www.linkedin.com/in/ashutoshv19/" }
```

Both return the same body.

```bash
curl "http://127.0.0.1:8000/profile?url=https://www.linkedin.com/in/ashutoshv19/"
```

<details>
<summary>Response shape</summary>

```json
{
  "profileUrl": "https://www.linkedin.com/in/ashutoshv19/",
  "publicIdentifier": "ashutoshv19",
  "profileUrn": "urn:li:fsd_profile:...",
  "firstName": "Ashutosh",
  "lastName": "Verma",
  "fullName": "Ashutosh Verma",
  "headline": "Full Stack Developer @ HCLTech | ...",
  "about": "...",
  "location": { "country": "IN", "geoUrn": "urn:li:fsd_geo:102335936" },
  "profilePicture": {
    "url": "https://media.licdn.com/.../scale_400_400/...",
    "sizes": { "100": "...", "200": "...", "400": "...", "800": "..." }
  },
  "backgroundPicture": { "url": "...", "sizes": {} },
  "experience": [
    {
      "title": "Full Stack Engineer",
      "company": "HCLTech",
      "companyUrn": "urn:li:fsd_company:1756",
      "location": "Lucknow",
      "description": "...",
      "startDate": "2025-10",
      "endDate": null,
      "current": true
    }
  ],
  "education": [
    {
      "school": "Amity University",
      "degree": "Bachelor of Technology",
      "fieldOfStudy": "Computational Science",
      "description": "CGPA 8.23",
      "startDate": "2021",
      "endDate": "2025"
    }
  ],
  "skills": ["Model Context Protocol (MCP)", "..."],
  "certifications": [
    { "name": "...", "authority": "...", "url": "...", "credentialId": "...",
      "issuedDate": "2025-03", "expiresDate": null }
  ],
  "languages": [{ "name": "...", "proficiency": "..." }],
  "projects": [{ "title": "...", "description": "...", "url": "...",
                 "startDate": "...", "endDate": "..." }],
  "courses": [], "honors": [], "volunteering": []
}
```
</details>

### `GET /health`

```json
{ "status": "ok", "credentialsConfigured": true }
```

### Errors

| Status | Meaning |
|---|---|
| 400 | The URL is not a `/in/<name>` profile URL |
| 404 | Profile does not exist, or is not visible to the logged-in account |
| 429 | LinkedIn is rate limiting the session |
| 502 | Cookie rejected or expired, or Voyager returned an error |

---

## Approach

Full reasoning, including the dead ends, is in
[`docs/adr/`](docs/adr/README.md). Summary below.

LinkedIn's web app runs on a private JSON API at
`https://www.linkedin.com/voyager/api`. It is not documented and not public,
but it is the same API their own frontend uses, so it has everything the
profile page shows. This project talks to it directly.

**How I found it.** I opened my own profile with DevTools recording, and
checked what the page requested. Two things stood out:

1. The profile page is **server-rendered**. The data arrives inside the HTML,
   so no XHR carries it on first load. Scrolling and background work is what
   exposes the API calls.
2. Those background calls all go to `/voyager/api/...`, carrying a
   `csrf-token` header whose value is just the `JSESSIONID` cookie.

**Authentication** is two cookies and one header:

| What | Value |
|---|---|
| `li_at` cookie | the login session |
| `JSESSIONID` cookie | session id |
| `csrf-token` header | the `JSESSIONID` value, quotes stripped |
| `x-restli-protocol-version` header | `2.0.0`, required or you get a 400 |
| `accept` header | `application/vnd.linkedin.normalized+json+2.1` |

That last header matters a lot. It makes Voyager answer in **normalized**
form: a flat `included` array where every object carries a `$type`. That is
much easier to parse than the nested default.

**Endpoints used.**

```
GET /identity/dash/profiles?q=memberIdentity&memberIdentity=<slug>
```

That returns the core profile: name, headline, about, images, and the
`entityUrn`. The URN is the key for everything else. Then nine section
finders, all fetched concurrently with `asyncio.gather`:

```
GET /identity/dash/profilePositions?q=viewee&profileUrn=<urn>
GET /identity/dash/profileEducations?q=viewee&profileUrn=<urn>
GET /identity/dash/profileSkills?q=viewee&profileUrn=<urn>
GET /identity/dash/profileCertifications?q=viewee&profileUrn=<urn>
GET /identity/dash/profileLanguages?q=viewee&profileUrn=<urn>
GET /identity/dash/profileProjects?q=viewee&profileUrn=<urn>
GET /identity/dash/profileCourses?q=viewee&profileUrn=<urn>
GET /identity/dash/profileHonors?q=viewee&profileUrn=<urn>
GET /identity/dash/profileVolunteerExperiences?q=viewee&profileUrn=<urn>
```

**A dead end worth recording.** Most existing LinkedIn scraper libraries use
`/identity/profiles/{slug}/profileView`, which used to return the whole
profile in one call. It now returns **410 Gone**. Those libraries are broken.
The `dash` finders above are the current replacement.

**Why not GraphQL.** Voyager also exposes
`/voyager/api/graphql?variables=(...)&queryId=<name>.<32-hex-hash>`. The hash
is generated per frontend build. Since LinkedIn now server-renders every
profile route, those hashes never appear in browser traffic on a profile page,
and they are not in the eagerly-loaded JS bundles either. The `dash` REST
finders need no hash, so they are both simpler and more stable.

**Redirects are normal, and they carry a rotated session.** Voyager answers
with a `302` pointing at the identical URL, and that response sets a **new**
`li_at`. LinkedIn rotates the session cookie underneath you.

This is the subtlest thing in the project and it is worth stating plainly,
because the obvious implementation is wrong:

> Build a fresh HTTP client per request and you discard the rotated `li_at`.
> The next request sends the superseded cookie, LinkedIn refuses it, and you
> get either a `403` or an endless redirect loop. The first request succeeds
> and every later one fails, which reads like a rate limit or a ban but is
> neither.

Three things follow from that, and all three are needed:

1. **One client for the app's lifetime**, built in the FastAPI lifespan hook.
   The cookie jar is the session; it has to survive between requests.
2. **Cookies are managed by hand, not by httpx's jar.** The jar is
   domain-aware. We seed `li_at` on `.linkedin.com`, LinkedIn sets the rotated
   one on `.www.linkedin.com`, and then *both* get sent. LinkedIn sees the
   stale copy and bounces forever. A plain dict keyed by cookie name gives one
   name one value. Redirects are followed manually so every hop resends the
   current cookies, and `csrf-token` is re-synced whenever `JSESSIONID`
   changes.
3. **The jar is written to `.session.json` on every rotation.** Without this,
   a restart falls back to whatever was pasted into `.env`, which LinkedIn may
   already have superseded — so the service works once, then 502s until you
   re-copy cookies by hand. The saved file outranks `.env` on startup. Writes
   go through a temp file and an atomic replace.

`MAX_REDIRECTS` is 4, so a genuinely dead session fails after four calls
instead of hammering LinkedIn twenty times.

**Images** are not returned as URLs. Voyager gives a `rootUrl` plus a list of
size `artifacts`. The real URL is `rootUrl + fileIdentifyingUrlPathSegment`.
The response exposes every size and picks the largest as the default `url`.

**Failure isolation.** The nine section calls use
`return_exceptions=True`. If LinkedIn changes or removes one finder, that
section comes back as `[]` and the rest of the profile still returns.

---

## Testing

```bash
uv run python test_parse.py
```

Runs against captured Voyager payloads. No network, no cookies needed. It
covers URL parsing, date ranges, current-job detection, image size selection,
the empty-section fallback, and the session logic: a rotated cookie is
absorbed and saved, `csrf-token` follows `JSESSIONID`, an empty cookie value
is treated as a deletion, a saved session beats `.env` on restart, and a
corrupt session file falls back instead of crashing.

---

## Known limitations

- **This violates LinkedIn's Terms of Service.** The account whose cookie you
  use can be restricted or banned. Use a throwaway account.
- **Cookies expire.** `li_at` nominally lasts a year but dies on logout or a
  password change. Rotation is handled (see below), expiry is not. When it
  finally dies every request returns 502 and you re-copy from the browser.
- **`.session.json` holds live credentials.** It is gitignored, but it is a
  plaintext file on disk. On a shared host, use a secrets store instead.
- **Rate limits are real and unpublished.** Each profile lookup costs ten
  requests. The client throttles itself to 3 in flight with a 0.4s gap
  (`MAX_CONCURRENCY` / `DELAY_BETWEEN_CALLS` in `linkedin.py`) so a lookup
  does not arrive as one burst. That is a courtesy, not a guarantee. Put a
  queue in front before running this at volume.
- **Location is a country code and a geo URN, not a city name.** The profile
  page shows "Lucknow, Uttar Pradesh, India", but that text is resolved
  server-side. `/identity/dash/geos/<urn>` returns 404, and the GraphQL geo
  query needs a build hash. Per-job `location` strings do come through.
- **Company and school logos are not included.** Positions carry
  `companyUrn` but resolving it to a logo needs another call per company.
- **Only what your account can see.** Out-of-network profiles may return
  partial data or 404.
- **No caching.** Every request hits LinkedIn. Add caching before deploying
  anywhere public.
- **Unofficial API, no stability promise.** Voyager can change any day.
  `profileView` already died this way.

---

## Deploying

Any host that runs a Python web service works. Render, Railway, or Fly.

- Build command: `uv sync --frozen`
- Start command: `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set `LINKEDIN_LI_AT` and `LINKEDIN_JSESSIONID` as environment variables in
  the host's dashboard. Never commit them.
- All three hosts terminate HTTPS for you.
