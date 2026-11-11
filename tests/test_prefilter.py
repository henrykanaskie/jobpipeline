from jobpipeline.prefilter import passes

PREFS = {"title_include": ["software engineer", "backend"],
         "title_exclude": ["senior", "sr", "intern"],
         "location_include": ["remote", "new york"]}


def test_include_exclude_and_location():
    assert passes("Software Engineer I", "New York, NY", PREFS)
    assert not passes("Senior Software Engineer", "Remote", PREFS)
    assert not passes("Sr. Backend Engineer", "Remote", PREFS)
    assert not passes("Software Engineer", "Austin, TX", PREFS)
    assert not passes("Product Designer", "Remote", PREFS)


def test_whole_words_only():
    # "intern" must not reject "Internal Tools"
    assert passes("Backend Engineer, Internal Tools", "Remote", PREFS)


def test_empty_location_list_means_anywhere():
    assert passes("Backend Engineer", None, {**PREFS, "location_include": []})
