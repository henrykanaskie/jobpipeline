"""Each source exposes NAME, parse(payload, board) -> list[posting dict] (pure), and either
url(board) for a single GET or fetch(session, board) -> payload for multi-request sources."""
from . import ashby, carpet, greenhouse, hackernews, lever, simplify, workday

SOURCES = {m.NAME: m for m in (carpet, greenhouse, lever, ashby, simplify, workday, hackernews)}
