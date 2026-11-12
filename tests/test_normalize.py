from jobpipeline.normalize import html_to_text, normalize_company, normalize_url


def test_company_suffixes_and_punctuation():
    assert normalize_company("Stripe, Inc.") == "stripe"
    assert normalize_company("STRIPE") == "stripe"
    assert normalize_company("Johnson & Johnson") == "johnson and johnson"
    assert normalize_company("Acme Holdings Co., Ltd.") == "acme holdings"


def test_url_strips_tracking_but_keeps_ids():
    a = normalize_url("https://Boards.Greenhouse.io/stripe/jobs/123/?utm_source=x&gh_src=abc#apply")
    assert a == "https://boards.greenhouse.io/stripe/jobs/123"
    assert normalize_url("https://x.com/job?gh_jid=5&utm_medium=y") == "https://x.com/job?gh_jid=5"


def test_html_to_text_double_escaped():
    out = html_to_text("&lt;p&gt;Hello &amp;amp; welcome&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;")
    assert [l for l in out.splitlines() if l] == ["Hello & welcome", "Python"]


def test_html_to_text_opening_p_is_a_break():
    # Hacker News uses <p> as a separator with no closing tag
    assert html_to_text("A | B<p>Body").splitlines()[0] == "A | B"
