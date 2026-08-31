"""One runnable check for the parsing logic. No network, no framework.

Run it with:  python test_parse.py
"""
import asyncio

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


def check_rotation():
    """A rotated cookie must be picked up and handed back to the caller."""
    client = Voyager("old-li-at", "ajax:111")
    assert client._jar["li_at"] == "old-li-at"
    assert client._headers["csrf-token"] == "ajax:111"

    # LinkedIn hands back a rotated li_at and a new JSESSIONID.
    asyncio.run(client._absorb(FakeResponse([
        "li_at=NEW-li-at; Path=/; Domain=.www.linkedin.com; HttpOnly",
        'JSESSIONID="ajax:222"; Path=/; Domain=.linkedin.com',
        "liap=true; Path=/",
        "lidc=; Path=/",  # a deletion, must be ignored
    ])))

    assert client._jar["li_at"] == "NEW-li-at"
    assert client._headers["csrf-token"] == "ajax:222", "csrf must track JSESSIONID"
    assert "lidc" not in client._jar, "empty value is a deletion, not a cookie"

    # The caller gets the new pair back, unquoted, ready to send next time.
    assert client.cookies == {"li_at": "NEW-li-at", "jsessionid": "ajax:222"}


def check_cookie_validation():
    """Cookies arrive from the network, so they are untrusted input."""
    # A ';' or a line break could forge extra cookies or extra headers.
    for bad in ["good; li_at=evil", "line\r\nX-Evil: 1"]:
        for pair in [(bad, "ajax:1"), ("li-at", bad)]:
            try:
                Voyager(*pair)
                raise AssertionError(f"should have rejected: {bad!r}")
            except LinkedInError as exc:
                assert exc.status == 400

    # Missing halves are rejected too. One cookie is not a session.
    for pair in [("", "ajax:1"), ("li-at", "")]:
        try:
            Voyager(*pair)
            raise AssertionError(f"should have rejected: {pair!r}")
        except LinkedInError as exc:
            assert exc.status == 400


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

    check_rotation()
    check_cookie_validation()

    print("all checks passed")


if __name__ == "__main__":
    main()
