"""Lever postings API (public, no key). board = {"token": "palantir", "company": "Palantir"}"""
from ._common import posting

NAME = "lever"


def url(board: dict) -> str:
    return f"https://api.lever.co/v0/postings/{board['token']}?mode=json"


def parse(payload: list, board: dict) -> list[dict]:
    out = []
    for j in payload:
        cats = j.get("categories") or {}
        text = "\n\n".join(filter(None, [
            j.get("descriptionPlain"),
            *(f"{l.get('text', '')}\n{l.get('content', '')}" for l in j.get("lists", [])),
            j.get("additionalPlain"),
        ]))
        out.append(posting(NAME, board["company"], j["text"], cats.get("location"),
                           j["hostedUrl"], text))
    return out
