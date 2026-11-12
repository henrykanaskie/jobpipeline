import os

import pytest

from jobpipeline import db


@pytest.fixture
def conn():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set")
    c = db.connect(url)
    c.execute("DROP TABLE IF EXISTS applications, postings, source_runs, score_calls CASCADE")
    c.commit()
    db.migrate(c)
    yield c
    c.close()
