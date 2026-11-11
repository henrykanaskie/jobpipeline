"""Greenhouse job board API (public, no key). board = {"token": "stripe", "company": "Stripe"}"""
from ..normalize import html_to_text
from ._common import posting

NAME = "greenhouse"


def url(board: dict) -> str:
    return f"https://boards-api.greenhouse.io/v1/boards/{board['token']}/jobs?content=true"


def parse(payload: dict, board: dict) -> list[dict]:
    return [
        posting(NAME, board["company"], j["title"], (j.get("location") or {}).get("name"),
                j["absolute_url"], html_to_text(j.get("content")))
        for j in payload.get("jobs", [])
    ]
