from jobpipeline import fulltext
from jobpipeline.sources import hackernews, workday

BOARD = {"token": "nvidia", "company": "NVIDIA",
         "url": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"}


def test_workday_site_parts_skip_locale():
    assert workday.site_parts(BOARD["url"]) == ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")
    assert workday.api_base(BOARD["url"]) == \
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite"


def test_workday_parse():
    payload = {"jobPostings": [
        {"title": "Software Engineer", "externalPath": "/job/US-CA-Santa-Clara/Software-Engineer_JR1",
         "locationsText": "US, CA, Santa Clara"},
        {"title": "No path"}]}
    [p] = workday.parse(payload, BOARD)
    assert p["url"] == ("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
                        "/job/US-CA-Santa-Clara/Software-Engineer_JR1")
    assert p["company"] == "nvidia" and p["full_text"] is None


def test_workday_fetch_paginates_and_stops(monkeypatch):
    calls = []

    def fake_post(sess, url, body):
        calls.append(body["offset"])
        if body["offset"] == 0:
            return {"total": 25, "jobPostings": [{"title": str(i), "externalPath": f"/job/x/{i}"} for i in range(20)]}
        return {"total": 0, "jobPostings": [{"title": str(i), "externalPath": f"/job/x/{i}"} for i in range(20, 25)]}
    monkeypatch.setattr(workday.http, "post_json", fake_post)
    monkeypatch.setattr(workday.time, "sleep", lambda s: None)
    assert len(workday.fetch(None, BOARD)["jobPostings"]) == 25 and calls == [0, 20]


def test_workday_detail_url_for_fulltext():
    url = "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/US-CA/Software-Engineer_JR1"
    assert fulltext._workday_api_url(url) == \
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/US-CA/Software-Engineer_JR1"
    assert fulltext._workday_api_url("https://boards.greenhouse.io/x/jobs/1") is None


def test_hackernews_parse():
    payload = {"children": [
        {"id": 101, "text": "Acme Robotics | Senior Backend Engineer | Remote (US) | $150k<p>We build robots."},
        {"id": 102, "text": "Just a comment with no header"},
        {"id": 103, "text": None},
        {"id": 104, "text": "Foo | NYC | ONSITE | Full-stack Developer<p>Details"}]}
    a, b = hackernews.parse(payload, {"token": "whoishiring"})
    assert (a["company_display"], a["title"], a["location"]) == ("Acme Robotics", "Senior Backend Engineer", "Remote (US)")
    assert a["url"] == "https://news.ycombinator.com/item?id=101" and "robots" in a["full_text"]
    assert (b["title"], b["location"]) == ("Full-stack Developer", "NYC")
