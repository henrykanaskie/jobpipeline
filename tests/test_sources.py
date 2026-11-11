from jobpipeline.sources import ashby, greenhouse, lever, simplify


def test_greenhouse():
    payload = {"jobs": [{"id": 1, "title": "Software Engineer, New Grad ",
                         "absolute_url": "https://boards.greenhouse.io/stripe/jobs/1",
                         "location": {"name": "Seattle, WA"}, "content": "&lt;p&gt;Build&lt;/p&gt;"}]}
    [p] = greenhouse.parse(payload, {"token": "stripe", "company": "Stripe, Inc."})
    assert p == {"source": "greenhouse", "company": "stripe", "company_display": "Stripe, Inc.",
                 "title": "Software Engineer, New Grad", "location": "Seattle, WA",
                 "url": "https://boards.greenhouse.io/stripe/jobs/1", "full_text": "Build"}


def test_lever_combines_description_and_lists():
    payload = [{"id": "a", "text": "Backend Engineer", "hostedUrl": "https://jobs.lever.co/x/a",
                "categories": {"location": "Remote"}, "descriptionPlain": "About",
                "lists": [{"text": "Requirements", "content": "<li>Go</li>"}]}]
    [p] = lever.parse(payload, {"token": "x", "company": "X"})
    assert p["location"] == "Remote" and "Requirements" in p["full_text"]


def test_ashby_skips_unlisted():
    payload = {"jobs": [
        {"title": "A", "jobUrl": "https://jobs.ashbyhq.com/r/1", "location": "NYC", "isListed": True},
        {"title": "B", "jobUrl": "https://jobs.ashbyhq.com/r/2", "location": "NYC", "isListed": False}]}
    assert [p["title"] for p in ashby.parse(payload, {"token": "r", "company": "Ramp"})] == ["A"]


def test_simplify_filters_inactive_and_uses_listing_company():
    payload = [
        {"company_name": "ICE", "title": "Dev", "url": "https://a.com/1", "locations": ["NY", "FL"],
         "active": True, "is_visible": True},
        {"company_name": "Old", "title": "Dev", "url": "https://a.com/2", "locations": [],
         "active": False, "is_visible": True}]
    [p] = simplify.parse(payload, {"token": "new-grad", "url": "u"})
    assert p["company"] == "ice" and p["location"] == "NY; FL" and p["full_text"] is None
