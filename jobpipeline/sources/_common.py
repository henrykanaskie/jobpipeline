from ..normalize import normalize_company, normalize_url


def posting(source: str, company: str, title: str, location: str | None, url: str,
            full_text: str | None) -> dict:
    return {
        "source": source,
        "company": normalize_company(company),
        "company_display": company,
        "title": title.strip(),
        "location": (location or "").strip() or None,
        "url": normalize_url(url),
        "full_text": full_text or None,
    }
