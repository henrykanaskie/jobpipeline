"""SimplifyJobs listings.json from their public GitHub repos.
board = {"token": "new-grad", "url": "https://raw.githubusercontent.com/..../listings.json"}
Company comes from each listing, not the board config."""
from ._common import posting

NAME = "simplify"


def url(board: dict) -> str:
    return board["url"]


def parse(payload: list, board: dict) -> list[dict]:
    return [
        posting(NAME, j["company_name"], j["title"], "; ".join(j.get("locations") or []),
                j["url"], None)   # Simplify has no description; Screening fetches it later
        for j in payload
        if j.get("active") and j.get("is_visible", True) and j.get("url")
    ]
