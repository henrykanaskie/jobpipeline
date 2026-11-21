import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from jobpipeline import prefilter
from jobpipeline.sources import hackernews

FIXTURES = Path(__file__).parent / "fixtures"
SEARCH = json.loads((FIXTURES / "hn_search.json").read_text())
ITEM = json.loads((FIXTURES / "hn_item.json").read_text())
BOARD = {"token": "whoishiring"}


def test_pick_thread_current_month_ignores_other_threads():
    now = datetime(2026, 11, 21, tzinfo=timezone.utc)
    assert hackernews.pick_thread(SEARCH["hits"], now)["objectID"] == "50338728"


def test_pick_thread_uses_last_month_only_early_in_the_month():
    hits = [h for h in SEARCH["hits"] if "November" not in h["title"]]
    assert hackernews.pick_thread(hits, datetime(2026, 11, 1, tzinfo=timezone.utc))["objectID"] == "49922569"
    with pytest.raises(hackernews.ThreadNotFound):
        hackernews.pick_thread(hits, datetime(2026, 11, 21, tzinfo=timezone.utc))


def test_pick_thread_january_falls_back_to_december():
    hits = [{"objectID": "1", "title": "Ask HN: Who is hiring? (December 2026)"}]
    assert hackernews.pick_thread(hits, datetime(2027, 1, 2, tzinfo=timezone.utc))["objectID"] == "1"


def test_fetch_reads_search_then_item(monkeypatch):
    urls = []

    def fake_get(sess, url):
        urls.append(url)
        return SEARCH if "search_by_date" in url else ITEM
    monkeypatch.setattr(hackernews.http, "get_json", fake_get)
    monkeypatch.setattr(hackernews, "pick_thread", lambda hits: hits[0])
    assert hackernews.fetch(None, BOARD) is ITEM
    assert urls[1] == "https://hn.algolia.com/api/v1/items/50338728"


def test_parse_fixture_is_conservative():
    posts = hackernews.parse(ITEM, BOARD)
    # 1003 has no role, 1004 starts with an update line, 1005 is deleted,
    # 1006 has a sentence where the company should be; the reply under 1001 is not top-level.
    assert [p["url"] for p in posts] == [f"https://news.ycombinator.com/item?id={i}"
                                         for i in (1001, 1002, 1007, 1008)]
    acme = posts[0]
    assert acme == {
        "source": "hackernews", "company": "acme robotics", "company_display": "Acme Robotics",
        "title": "Senior Backend Engineer", "location": "REMOTE (US)",
        "url": "https://news.ycombinator.com/item?id=1001",
        "full_text": acme["full_text"]}
    assert acme["full_text"].startswith("Acme Robotics (YC W24) | Senior Backend Engineer")
    assert "warehouse robots" in acme["full_text"]


def test_parse_comment_fields():
    by_id = {c["id"]: c for c in ITEM["children"]}
    acme = hackernews.parse_comment(by_id[1001])
    assert acme["remote"] is True and acme["apply_url"] == "https://acme.example/jobs/backend"

    lumen = hackernews.parse_comment(by_id[1002])
    assert (lumen["title"], lumen["location"], lumen["remote"]) == \
        ("Software Engineer, New Grad", "Austin, TX; HYBRID", False)

    field = hackernews.parse_comment(by_id[1007])
    assert field["company"] == "Fieldwork.io"
    assert field["apply_url"] == "https://fieldwork.example/careers"   # HN links skipped

    north = hackernews.parse_comment(by_id[1008])
    assert north["remote"] is False and north["location"] == "London, UK; no remote"


def test_remote_flag_is_added_to_location_for_the_prefilter():
    p = hackernews.parse_comment({"id": 5, "text": "Zed Co | Platform Engineer | work remotely from anywhere"})
    assert p["remote"] is True
    assert prefilter.passes("Platform Engineer", p["location"], {"location_include": ["remote"]})


# --- the second pass: postings that keep the role out of the header ----------

def _c(cid, *lines):
    return {"id": cid, "text": "<p>".join(lines)}


def test_role_is_recovered_from_a_bulleted_body():
    p = hackernews.parse_comment(_c(1, "SwingVision | Berkeley, CA | Full time + Internships",
                                    "SwingVision turns a phone camera into line-calling.",
                                    "- Head of Machine Learning: https://jobs.example/a",
                                    "- Machine Learning Engineer: https://jobs.example/b"))
    assert p["title"] == "Head of Machine Learning"
    assert p["company"] == "SwingVision" and p["location"] == "Berkeley, CA"


def test_body_role_prefers_the_line_after_an_explicit_lead_in():
    p = hackernews.parse_comment(_c(2, "NEO Holdings | Malibu, CA | ONSITE",
                                    "We are building the base layer for tokenized commodities.",
                                    "Roles currently available:",
                                    "VP of Engineering: owns the platform end to end, from on-chain "
                                    "contracts to the trading engine and the customer-facing API.",
                                    "Lead Product Manager: works with our partners."))
    assert p["title"] == "VP of Engineering"


def test_a_sentence_header_names_its_own_role():
    p = hackernews.parse_comment(_c(3, "Duranta (https://getduranta.com/) is hiring a computer vision "
                                       "engineer, enterprise account representative, and sales reps.",
                                    "The jobs are worked on site in Bengaluru."))
    assert p["company"] == "Duranta" and p["title"] == "computer vision engineer"


def test_status_updates_and_fragments_are_still_skipped():
    assert hackernews.parse_comment(_c(4, "UPDATE (Nov 13): We're no longer taking applications "
                                           "for these roles.", "Thanks to everyone who applied.")) is None
    assert hackernews.parse_comment(_c(5, "Apply here: https://tally.example/r/abc")) is None
    assert hackernews.parse_comment(_c(6, "Location: Huntington Beach, CA, USA")) is None
    assert hackernews.parse_comment(_c(7, "India")) is None


def test_a_dev_domain_is_not_a_role():
    # "careers@estuary.dev" must not read as a developer job.
    assert hackernews.parse_comment(_c(8, "Estuary | US-Based / Remote | Full-time",
                                       "Estuary builds streaming data pipelines.",
                                       "To apply: Email your resume to careers@estuary.dev")) is None


def test_roles_outside_engineering_are_read_from_the_header():
    p = hackernews.parse_comment(_c(9, "Charly | Sales / Account Executive GovTech | "
                                      "ONSITE Berlin, Germany | Full-time"))
    assert p["title"] == "Sales / Account Executive GovTech"

    phd = hackernews.parse_comment(_c(10, "University of Cambridge | PhD in Earth Observation | ONSITE | UK"))
    assert phd["title"] == "PhD in Earth Observation"


def test_strict_board_restores_header_only_parsing():
    body_only = _c(11, "Oklo | Remote (US) | Full time",
                   "Join us in pioneering the next generation of nuclear reactors!",
                   "We are hiring for:",
                   "- Software Engineer: https://jobs.example/oklo")
    payload = {"children": [body_only]}
    assert hackernews.parse(payload, {"token": "whoishiring"})[0]["title"] == "Software Engineer"
    assert hackernews.parse(payload, {"token": "whoishiring", "strict": True}) == []


def test_recovery_still_needs_both_a_company_and_a_role():
    # A header with a company but nothing anywhere that reads as a job.
    assert hackernews.parse_comment(_c(12, "Blackbird | Dev Shop | Remote (US only) | Contract",
                                       "We take on contract work for startups.")) is None
