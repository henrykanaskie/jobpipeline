from datetime import datetime, timezone

import pytest

from jobpipeline.sources import carpet

NOW = datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc)


def _feed(generated="2026-11-12T23:17:08.715Z", jobs=None):
    return {"generatedAt": generated, "jobs": jobs if jobs is not None else [
        {"company": "Arcfield", "title": "Enterprise Data Systems Engineer", "location": "Chantilly, Virginia · United States",
         "source": "icims", "posted_at": "2026-11-12T22:57:00.000Z",
         "absolute_url": "https://careers.arcfield.com/jobs/8924?icims=1", "track": "data", "new_grad": False},
        {"company": "Acme", "title": "Software Engineer I", "location": "Remote", "source": "workday",
         "posted_at": "2026-11-01T00:00:00.000Z", "absolute_url": "https://acme.wd1.myworkdayjobs.com/ext/job/x_1",
         "track": "software", "new_grad": True},
        {"company": "Old Co", "title": "Developer", "location": "NYC", "source": "greenhouse",
         "posted_at": "2020-10-27T18:32:40.993Z", "absolute_url": "https://boards.greenhouse.io/old/jobs/1",
         "track": "software", "new_grad": False},
        {"company": "PM Co", "title": "Product Manager", "location": "SF", "source": "lever",
         "posted_at": "2026-11-10T00:00:00.000Z", "absolute_url": "https://jobs.lever.co/pm/1",
         "track": "product", "new_grad": True}]}


def test_maps_fields_and_keeps_upstream_source():
    rows = carpet.parse(_feed(), {"token": "carpet"}, now=NOW)
    assert len(rows) == 4
    assert rows[0] == {"source": "carpet/icims", "company": "arcfield", "company_display": "Arcfield",
                       "title": "Enterprise Data Systems Engineer", "location": "Chantilly, Virginia · United States",
                       "url": "https://careers.arcfield.com/jobs/8924?icims=1", "full_text": None}


def test_filters_track_new_grad_and_age():
    board = {"token": "carpet", "tracks": ["software", "data"], "max_age_days": 60}
    assert [r["company"] for r in carpet.parse(_feed(), board, now=NOW)] == ["arcfield", "acme"]
    assert [r["company"] for r in carpet.parse(_feed(), {**board, "new_grad_only": True}, now=NOW)] == ["acme"]


def test_stale_feed_raises_so_crawler_alerts():
    with pytest.raises(carpet.StaleFeed):
        carpet.parse(_feed(generated="2026-11-12T10:00:00Z"), {"token": "carpet"}, now=NOW)
    with pytest.raises(carpet.StaleFeed):
        carpet.parse({"jobs": []}, {"token": "carpet"}, now=NOW)


def test_mixed_timestamp_formats():
    jobs = [{"company": "A", "title": "SWE", "source": "oracle", "absolute_url": "https://a/1", "track": "software",
             "posted_at": "2026-11-01 08:00:00"},                    # no timezone
            {"company": "B", "title": "SWE", "source": "oracle", "absolute_url": "https://b/1", "track": "software",
             "posted_at": "not a date"},
            {"company": "C", "title": "SWE", "source": "oracle", "absolute_url": "https://c/1", "track": "software",
             "posted_at": "2019-01-01T00:00:00"}]                    # too old
    rows = carpet.parse(_feed(jobs=jobs), {"token": "carpet", "max_age_days": 60}, now=NOW)
    assert [r["company"] for r in rows] == ["a", "b"]
