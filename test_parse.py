"""One runnable check for the parsing logic. No network, no framework.

Run it with:  python test_parse.py
"""
import json
import tempfile
from pathlib import Path

from linkedin import LinkedInError, Voyager, parse_profile, slug_from_url

# Trimmed real Voyager shapes, captured from the live API.
CORE = {
    "publicIdentifier": "ashutoshv19",
    "entityUrn": "urn:li:fsd_profile:ACoAAD",
    "firstName": "Ashutosh",
    "lastName": "Verma",
    "headline": "Full Stack Developer @ HCLTech",
    "summary": "About text.",
    "location": {"countryCode": "IN"},
    "geoLocation": {"geoUrn": "urn:li:fsd_geo:102335936"},
    "profilePicture": {
        "displayImageReference": {
            "vectorImage": {
                "rootUrl": "https://media.licdn.com/dms/image/pic-",
                "artifacts": [
                    {"width": 100, "fileIdentifyingUrlPathSegment": "100.jpg"},
                    {"width": 400, "fileIdentifyingUrlPathSegment": "400.jpg"},
                ],
            }
        }
    },
}

SECTIONS = {
    "experience": {"included": [{
        "$type": "com.linkedin.voyager.dash.identity.profile.Position",
        "title": "Full Stack Engineer",
        "companyName": "HCLTech",
        "locationName": "Lucknow",
        "dateRange": {"start": {"month": 10, "year": 2025}},
    }]},
    "education": {"included": [{
        "$type": "com.linkedin.voyager.dash.identity.profile.Education",
        "schoolName": "Amity University",
        "degreeName": "Bachelor of Technology",
        "fieldOfStudy": "Computational Science",
        "dateRange": {"start": {"year": 2021}, "end": {"year": 2025}},
    }]},
    "skills": {"included": [
        {"$type": "com.linkedin.voyager.dash.identity.profile.Skill", "name": "Python"},
        {"$type": "com.linkedin.voyager.dash.identity.profile.Skill", "name": "React"},
    ]},
    # A section that failed upstream comes through as {} and must not crash us.
    "projects": {},
}


class FakeResponse:
    """Just enough of an httpx response to exercise cookie absorbing."""

    def __init__(self, set_cookies):
        self.headers = _Headers(set_cookies)


class _Headers:
    def __init__(self, set_cookies):
        self._set_cookies = set_cookies

    def get_list(self, name):
        return self._set_cookies if name == "set-cookie" else []


def check_session_persistence():
    """A rotated cookie must survive a restart, or the session dies."""
    import asyncio

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "session.json"

        first = Voyager("old-li-at", "ajax:111", session_file=path)
        assert first._jar["li_at"] == "old-li-at"
        assert first._headers["csrf-token"] == "ajax:111"

        # LinkedIn hands back a rotated li_at and a new JSESSIONID.
        asyncio.run(first._absorb(FakeResponse([
            "li_at=NEW-li-at; Path=/; Domain=.www.linkedin.com; HttpOnly",
            'JSESSIONID="ajax:222"; Path=/; Domain=.linkedin.com',
            "liap=true; Path=/",
            "lidc=; Path=/",  # a deletion, must be ignored
        ])))

        assert first._jar["li_at"] == "NEW-li-at"
        assert first._headers["csrf-token"] == "ajax:222", "csrf must track JSESSIONID"
        assert "lidc" not in first._jar, "empty value is a deletion, not a cookie"
        assert path.exists(), "rotation should have been written to disk"

        saved = json.loads(path.read_text("utf-8"))
        assert saved["li_at"] == "NEW-li-at"

        # A restart re-reads .env, but the saved session must win.
        second = Voyager("old-li-at", "ajax:111", session_file=path)
        assert second._jar["li_at"] == "NEW-li-at", "restart lost the rotated cookie"
        assert second._headers["csrf-token"] == "ajax:222"

        # A corrupt file must not crash startup.
        path.write_text("{not json", "utf-8")
        third = Voyager("env-li-at", "ajax:333", session_file=path)
        assert third._jar["li_at"] == "env-li-at", "should fall back to .env"


def main():
    # URL parsing
    assert slug_from_url("https://www.linkedin.com/in/ashutoshv19/") == "ashutoshv19"
    assert slug_from_url("linkedin.com/in/foo-bar-123?trk=x") == "foo-bar-123"
    for bad in ["", "https://www.linkedin.com/company/hcltech", "not a url"]:
        try:
            slug_from_url(bad)
            raise AssertionError(f"should have rejected: {bad!r}")
        except LinkedInError:
            pass

    result = parse_profile(CORE, SECTIONS)

    assert result["fullName"] == "Ashutosh Verma"
    assert result["location"]["country"] == "IN"
    assert result["about"] == "About text."

    # Biggest artifact wins for the main image URL.
    assert result["profilePicture"]["url"].endswith("400.jpg")
    assert result["backgroundPicture"] is None

    job = result["experience"][0]
    assert job["startDate"] == "2025-10"
    assert job["endDate"] is None
    assert job["current"] is True, "no end date means still working there"

    school = result["education"][0]
    assert (school["startDate"], school["endDate"]) == ("2021", "2025")

    assert result["skills"] == ["Python", "React"]

    # Missing / failed sections come back empty, not missing.
    assert result["projects"] == []
    assert result["languages"] == []

    check_session_persistence()

    print("all checks passed")


if __name__ == "__main__":
    main()
