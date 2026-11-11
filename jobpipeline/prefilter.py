"""Keyword pre-filter: decides which postings are worth an LLM call. Pure, no I/O."""
import re


def _any_phrase(text: str, phrases: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(p.lower())}\b", text) for p in phrases)


def passes(title: str, location: str | None, prefs: dict) -> bool:
    t = title.lower()
    if _any_phrase(t, prefs.get("title_exclude") or []):
        return False
    include = prefs.get("title_include") or []
    if include and not _any_phrase(t, include):
        return False
    locs = prefs.get("location_include") or []
    if locs and not _any_phrase((location or "").lower(), locs):
        return False
    return True
