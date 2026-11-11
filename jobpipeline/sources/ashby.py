"""Ashby job board API (public, no key). board = {"token": "ramp", "company": "Ramp"}"""
from ._common import posting

NAME = "ashby"


def url(board: dict) -> str:
    return f"https://api.ashbyhq.com/posting-api/job-board/{board['token']}"


def parse(payload: dict, board: dict) -> list[dict]:
    return [
        posting(NAME, board["company"], j["title"], j.get("location"),
                j.get("jobUrl") or j["applyUrl"], j.get("descriptionPlain"))
        for j in payload.get("jobs", [])
        if j.get("isListed", True)
    ]
