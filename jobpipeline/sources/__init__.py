"""Each source exposes parse(payload, board) -> list[posting dict] (pure) and URL(board)."""
from . import ashby, greenhouse, lever, simplify

SOURCES = {m.NAME: m for m in (greenhouse, lever, ashby, simplify)}
