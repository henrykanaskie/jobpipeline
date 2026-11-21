import json
from pathlib import Path

import pytest

from jobpipeline import fulltext
from jobpipeline.sources import workday

# Two pages trimmed from a live Salesforce response (Nov 2026), plus two postings with
# missing fields. Workday reports `total` only on the first page.
PAGES = json.loads((Path(__file__).parent / "fixtures" / "workday_pages.json").read_text())
BOARD = {"token": "salesforce", "company": "Salesforce", "host": "salesforce.wd12.myworkdayjobs.com",
         "tenant": "salesforce", "site": "External_Career_Site", "search": "software engineer"}


class FakeResponse:
    def __init__(self, data=None, status=200, headers=None, text=None):
        self._data, self.status_code, self.text = data, status, text
        self.headers = headers or {"content-type": "application/json"}

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


@pytest.fixture
def fake_http(monkeypatch):
    calls = []
    responses = []

    def fake_request(sess, method, url, **kw):
        calls.append((method, url, kw))
        return responses.pop(0)
    monkeypatch.setattr(workday.http, "request", fake_request)
    monkeypatch.setattr(workday.time, "sleep", lambda s: None)
    monkeypatch.setattr(workday, "PAGE_SIZE", 3)
    return calls, responses


def test_fetch_pages_until_total(fake_http):
    calls, responses = fake_http
    responses += [FakeResponse(PAGES[0]), FakeResponse(PAGES[1])]
    payload = workday.fetch(None, BOARD)
    assert len(payload["jobPostings"]) == 7 and payload["total"] == 5
    assert [c[2]["json"]["offset"] for c in calls] == [0, 3]
    assert calls[0][1] == "https://salesforce.wd12.myworkdayjobs.com/wday/cxs/salesforce/External_Career_Site/jobs"
    assert calls[0][2]["json"]["searchText"] == "software engineer"
    assert calls[0][2]["allow_redirects"] is False


def test_fetch_respects_max_postings(fake_http):
    calls, responses = fake_http
    responses += [FakeResponse({**PAGES[0], "total": 500})]
    payload = workday.fetch(None, {**BOARD, "max_postings": 3})
    assert len(calls) == 1 and len(payload["jobPostings"]) == 3


def test_fetch_maintenance_redirect_raises(fake_http):
    _, responses = fake_http
    responses.append(FakeResponse(status=303, headers={"location": "https://community.workday.com/maintenance-page"}))
    with pytest.raises(workday.WorkdayError, match="maintenance"):
        workday.fetch(None, BOARD)


@pytest.mark.parametrize("resp", [FakeResponse(text="<html>", headers={"content-type": "text/html"}),
                                  FakeResponse({"errorCode": "HTTP_404"}),
                                  FakeResponse(["not", "a", "dict"])])
def test_fetch_unexpected_responses_raise(fake_http, resp):
    _, responses = fake_http
    responses.append(resp)
    with pytest.raises(workday.WorkdayError):
        workday.fetch(None, BOARD)


def test_parse_fixture_skips_missing_fields_and_expands_multi_location():
    posts = workday.parse({"jobPostings": PAGES[0]["jobPostings"] + PAGES[1]["jobPostings"]}, BOARD)
    assert len(posts) == 5
    first = posts[0]
    assert first == {
        "source": "workday", "company": "salesforce", "company_display": "Salesforce",
        "title": "LMTS - Lead AI/ML Engineer (LLM Post-Training)",
        "location": "India - Bangalore (+1 more)",
        "url": ("https://salesforce.wd12.myworkdayjobs.com/External_Career_Site/job/India---Bangalore/"
                "LMTS---Lead-AI-ML-Engineer--LLM-Post-Training-_JR368314"),
        "full_text": None}
    assert posts[1]["location"] == "Mexico - Mexico City"


def test_parse_all_postings_malformed_raises():
    with pytest.raises(workday.WorkdayError):
        workday.parse({"jobPostings": [{"title": "x"}, {"externalPath": "/job/a/b"}]}, BOARD)


def test_parse_empty_is_zero_results_not_error():
    assert workday.parse({"total": 0, "jobPostings": []}, BOARD) == []


def test_board_parts_from_url_or_explicit_keys():
    assert workday.board_parts({"url": "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite"}) == \
        ("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite")
    assert workday.board_parts(BOARD) == ("salesforce.wd12.myworkdayjobs.com", "salesforce", "External_Career_Site")
    with pytest.raises(ValueError):
        workday.board_parts({"token": "x", "host": "a.wd1.myworkdayjobs.com"})


def test_myworkdaysite_urls():
    url = "https://wd1.myworkdaysite.com/en-US/recruiting/acme/Careers"
    assert workday.site_parts(url) == ("wd1.myworkdaysite.com", "acme", "Careers")
    [p] = workday.parse({"jobPostings": [{"title": "SWE", "externalPath": "/job/Remote/SWE_R1"}]},
                        {"company": "Acme", "url": url})
    assert p["url"] == "https://wd1.myworkdaysite.com/recruiting/acme/Careers/job/Remote/SWE_R1"
    assert fulltext._workday_api_url(p["url"]) == \
        "https://wd1.myworkdaysite.com/wday/cxs/acme/Careers/job/Remote/SWE_R1"
