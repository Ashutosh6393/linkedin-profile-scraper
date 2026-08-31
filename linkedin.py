"""Reverse-engineered LinkedIn Voyager client.

Voyager is LinkedIn's own private JSON API - the same one their web app talks to.
We authenticate with a normal logged-in session cookie. No browser involved.
"""
import asyncio
import re
from urllib.parse import unquote

import httpx

BASE = "https://www.linkedin.com/voyager/api"

# Each of these is a "finder": ask for one kind of profile section by profile URN.
# Found by probing. The old /identity/profiles/{slug}/profileView is 410 Gone.
SECTION_FINDERS = {
    "experience": "profilePositions",
    "education": "profileEducations",
    "skills": "profileSkills",
    "certifications": "profileCertifications",
    "languages": "profileLanguages",
    "projects": "profileProjects",
    "courses": "profileCourses",
    "honors": "profileHonors",
    "volunteering": "profileVolunteerExperiences",
}


# Be gentle. One profile costs 10 requests; firing them all at once looks like
# a bot. Three at a time with a small gap looks like a person browsing.
MAX_CONCURRENCY = 3
DELAY_BETWEEN_CALLS = 0.4
# LinkedIn answers the first hit with a 302 to the same URL. One hop is normal;
# more than a couple means the session is dead, so fail fast instead of looping.
MAX_REDIRECTS = 4


class LinkedInError(Exception):
    """Raised when Voyager answers with something we cannot use."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def slug_from_url(url: str) -> str:
    """Pull `ashutoshv19` out of https://www.linkedin.com/in/ashutoshv19/."""
    match = re.search(r"/in/([^/?#]+)", (url or "").strip())
    if not match:
        raise LinkedInError("Not a LinkedIn profile URL (expected /in/<name>).", 400)
    slug = unquote(match.group(1)).strip()
    if not slug:
        raise LinkedInError("Profile URL has an empty handle.", 400)
    return slug


# --- small parsing helpers -------------------------------------------------

def _date(node):
    """{'year': 2025, 'month': 10} -> '2025-10'."""
    if not node or not node.get("year"):
        return None
    parts = [str(node["year"])]
    for key in ("month", "day"):
        if node.get(key):
            parts.append(f"{node[key]:02d}")
    return "-".join(parts)


def _span(node):
    """A dateRange -> (start, end). end is None while it is ongoing."""
    node = node or {}
    return _date(node.get("start")), _date(node.get("end"))


def _image(node):
    """Rebuild a usable image URL. LinkedIn splits it into root + size artifacts."""
    vector = ((node or {}).get("displayImageReference") or {}).get("vectorImage") or {}
    root = vector.get("rootUrl")
    artifacts = [
        a for a in (vector.get("artifacts") or [])
        if a.get("fileIdentifyingUrlPathSegment")
    ]
    if not root or not artifacts:
        return None
    biggest = max(artifacts, key=lambda a: a.get("width") or 0)
    return {
        "url": root + biggest["fileIdentifyingUrlPathSegment"],
        "sizes": {
            str(a.get("width")): root + a["fileIdentifyingUrlPathSegment"]
            for a in artifacts if a.get("width")
        },
    }


def _of_type(payload, suffix):
    """Voyager returns a flat `included` list. Pick entries we want by $type."""
    return [
        item for item in (payload or {}).get("included", [])
        if str(item.get("$type", "")).endswith(suffix)
    ]


# --- section mappers -------------------------------------------------------

def _experience(item):
    start, end = _span(item.get("dateRange"))
    return {
        "title": item.get("title"),
        "company": item.get("companyName"),
        "companyUrn": item.get("companyUrn"),
        "location": item.get("locationName"),
        "description": item.get("description"),
        "startDate": start,
        "endDate": end,
        "current": start is not None and end is None,
    }


def _education(item):
    start, end = _span(item.get("dateRange"))
    return {
        "school": item.get("schoolName"),
        "degree": item.get("degreeName"),
        "fieldOfStudy": item.get("fieldOfStudy"),
        "description": item.get("description"),
        "startDate": start,
        "endDate": end,
    }


def _certification(item):
    start, end = _span(item.get("dateRange"))
    return {
        "name": item.get("name"),
        "authority": item.get("authority"),
        "url": item.get("url"),
        "credentialId": item.get("licenseNumber"),
        "issuedDate": start,
        "expiresDate": end,
    }


def _project(item):
    start, end = _span(item.get("dateRange"))
    return {
        "title": item.get("title"),
        "description": item.get("description"),
        "url": item.get("url"),
        "startDate": start,
        "endDate": end,
    }


def _volunteering(item):
    start, end = _span(item.get("dateRange"))
    return {
        "role": item.get("role"),
        "organization": item.get("companyName"),
        "cause": item.get("cause"),
        "description": item.get("description"),
        "startDate": start,
        "endDate": end,
    }


def _honor(item):
    return {
        "title": item.get("title"),
        "issuer": item.get("issuer"),
        "description": item.get("description"),
        "issuedDate": _date(item.get("issueDate")),
    }


# name -> ($type suffix to match, how to map one row)
SECTION_SPEC = {
    "experience": ("profile.Position", _experience),
    "education": ("profile.Education", _education),
    "skills": ("profile.Skill", lambda i: i.get("name")),
    "certifications": ("profile.Certification", _certification),
    "languages": ("profile.Language",
                  lambda i: {"name": i.get("name"), "proficiency": i.get("proficiency")}),
    "projects": ("profile.Project", _project),
    "courses": ("profile.Course",
                lambda i: {"name": i.get("name"), "number": i.get("number")}),
    "honors": ("profile.Honor", _honor),
    "volunteering": ("profile.VolunteerExperience", _volunteering),
}


def parse_profile(core, sections, profile_url=None):
    """Turn raw Voyager payloads into the JSON we hand back. Pure - no network."""
    out = {
        "profileUrl": profile_url
        or f"https://www.linkedin.com/in/{core.get('publicIdentifier')}/",
        "publicIdentifier": core.get("publicIdentifier"),
        "profileUrn": core.get("entityUrn"),
        "firstName": core.get("firstName"),
        "lastName": core.get("lastName"),
        "fullName": " ".join(
            x for x in [core.get("firstName"), core.get("lastName")] if x
        ) or None,
        "headline": core.get("headline"),
        "about": core.get("summary"),
        "location": {
            "country": (core.get("location") or {}).get("countryCode"),
            "geoUrn": (core.get("geoLocation") or {}).get("geoUrn"),
        },
        "profilePicture": _image(core.get("profilePicture")),
        "backgroundPicture": _image(core.get("backgroundPicture")),
    }
    for name, (suffix, mapper) in SECTION_SPEC.items():
        rows = [mapper(item) for item in _of_type(sections.get(name), suffix)]
        out[name] = [r for r in rows if r]
    return out


# --- the client ------------------------------------------------------------

class Voyager:
    """Talks to Voyager using a logged-in session cookie."""

    def __init__(self, li_at: str, jsessionid: str, timeout: float = 20.0):
        if not li_at or not jsessionid:
            raise LinkedInError("li_at and jsessionid are both required.", 400)
        # Cookies arrive in a request body, so they are untrusted input. They
        # get pasted straight into a Cookie header; a ';' or a newline there
        # would let a caller forge extra cookies or extra headers.
        if any(c in li_at + jsessionid for c in ";\r\n"):
            raise LinkedInError(
                "Cookie values must not contain ';' or line breaks.", 400
            )
        # The CSRF token is literally the JSESSIONID value, quotes stripped.
        token = jsessionid.strip('"')
        self._gate = asyncio.Semaphore(MAX_CONCURRENCY)
        # We keep cookies in a plain dict and send them ourselves. httpx's jar
        # is domain-aware, and LinkedIn sets its rotated li_at on a different
        # domain than the one we seed. Both then get sent, LinkedIn sees the
        # stale copy, and bounces us forever. One name -> one value avoids it.
        self._jar = {"li_at": li_at, "JSESSIONID": f'"{token}"'}
        self._jar_lock = asyncio.Lock()
        self._headers = {
            "csrf-token": token,
            "x-restli-protocol-version": "2.0.0",
            # This accept header makes Voyager return the flat `included` list.
            "accept": "application/vnd.linkedin.normalized+json+2.1",
            "x-li-lang": "en_US",
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        }
        # ONE long-lived client on purpose. LinkedIn silently rotates li_at and
        # hands the new one back via Set-Cookie. A client built per request
        # throws that away, the old cookie dies, and every later call 403s.
        # Redirects are followed by hand below so each hop resends fresh cookies.
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def aclose(self):
        await self._client.aclose()

    @property
    def cookies(self) -> dict:
        """The session as it stands now, in the shape a caller sends it back.

        LinkedIn rotates these mid-session, so by the end of a request they may
        differ from what arrived. Nothing is stored server-side, so handing them
        back is the only way the caller can stay in step.
        """
        return {
            "li_at": self._jar.get("li_at"),
            "jsessionid": self._headers["csrf-token"],
        }

    async def _absorb(self, response):
        """Take any rotated cookie LinkedIn hands back and keep it."""
        async with self._jar_lock:
            for raw in response.headers.get_list("set-cookie"):
                pair = raw.split(";", 1)[0].strip()
                if "=" not in pair:
                    continue
                name, value = (part.strip() for part in pair.split("=", 1))
                if not value or value in ('""', '"-"', "-"):
                    continue  # a deletion, not a new value
                self._jar[name] = value
                if name == "JSESSIONID":
                    # csrf-token must always match the current JSESSIONID.
                    self._headers["csrf-token"] = value.strip('"')

    async def _send(self, path, params):
        """One GET, following LinkedIn's self-redirects with current cookies."""
        url = f"{BASE}{path}"
        for _ in range(MAX_REDIRECTS):
            async with self._jar_lock:
                headers = dict(self._headers)
                headers["cookie"] = "; ".join(
                    f"{k}={v}" for k, v in self._jar.items()
                )
            response = await self._client.get(url, params=params, headers=headers)
            await self._absorb(response)
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("location")
            if not location:
                return response
            # LinkedIn redirects to the same URL; params are already in it.
            url, params = location, None
        raise LinkedInError(
            "LinkedIn kept redirecting, which means the session is dead. Copy "
            "fresh li_at and JSESSIONID cookies out of the browser.", 502
        )

    async def _get(self, path, params):
        # The semaphore keeps us to a few requests at a time instead of a burst.
        async with self._gate:
            response = await self._send(path, params)
            await asyncio.sleep(DELAY_BETWEEN_CALLS)
        if response.status_code in (401, 403):
            raise LinkedInError(
                "LinkedIn rejected the session cookie. Copy fresh li_at and "
                "JSESSIONID cookies out of the browser.", 502
            )
        if response.status_code == 429:
            raise LinkedInError("LinkedIn is rate limiting this session.", 429)
        if response.status_code == 404:
            raise LinkedInError("Profile not found.", 404)
        if response.status_code >= 400:
            raise LinkedInError(
                f"Voyager returned {response.status_code} for {path}.", 502
            )
        # A login bounce or a challenge page answers 200 with HTML, not JSON.
        # Say so clearly instead of dying on a JSON decode error.
        if "json" not in response.headers.get("content-type", ""):
            raise LinkedInError(
                "LinkedIn answered with a non-JSON page. The session is most "
                "likely expired or challenged. Refresh the cookies.", 502
            )
        return response.json()

    async def fetch_profile(self, url: str) -> dict:
        slug = slug_from_url(url)
        payload = await self._get(
            "/identity/dash/profiles",
            {"q": "memberIdentity", "memberIdentity": slug},
        )
        core = next(iter(_of_type(payload, "profile.Profile")), None)
        if not core:
            raise LinkedInError(
                "Profile not found or not visible to this account.", 404
            )

        urn = core["entityUrn"]
        names = list(SECTION_FINDERS)
        # All nine sections are independent, so fetch them at the same time.
        results = await asyncio.gather(
            *[
                self._get(
                    f"/identity/dash/{SECTION_FINDERS[n]}",
                    # Without count, finders return only the first 20 rows.
                    {"q": "viewee", "profileUrn": urn, "count": 100},
                )
                for n in names
            ],
            return_exceptions=True,
        )

        # One dead section should not sink the whole response.
        sections = {
            n: (r if not isinstance(r, Exception) else {})
            for n, r in zip(names, results)
        }
        return parse_profile(core, sections, profile_url=url)
