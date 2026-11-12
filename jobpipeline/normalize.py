"""Pure helpers for turning source data into comparable values."""
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "plc", "gmbh", "ag", "sa", "lp", "llp", "pbc",
}
_TRACKING_PARAMS = {"ref", "source", "src", "gh_src", "lever-source", "lever-origin",
                    "mobile", "needsredirect"}


def normalize_company(name: str) -> str:
    """'Stripe, Inc.' -> 'stripe'; 'The Trade Desk' -> 'the trade desk'."""
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    words = s.split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def normalize_url(url: str) -> str:
    """Lowercase scheme/host, drop fragments, tracking params and trailing slashes."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", parts.netloc.lower(), path,
                       urlencode(sorted(query)), ""))


def html_to_text(raw: str | None) -> str:
    """Greenhouse returns HTML-escaped HTML; collapse it to plain text."""
    if not raw:
        return ""
    s = html.unescape(html.unescape(raw))
    s = re.sub(r"<(br|p|/p|li|/li|/h\d|/div)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n\n", s).strip()


def normalize_title(title: str) -> str:
    """'Software Engineer, New Grad (2027)' -> 'software engineer new grad 2027'."""
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", title.lower()).split())
