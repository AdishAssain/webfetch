import httpx

from .config import FIRECRAWL_API_KEY, FIRECRAWL_SCRAPE_URL


def scrape(url: str, timeout: float = 60.0) -> tuple[str, str]:
    resp = httpx.post(
        FIRECRAWL_SCRAPE_URL,
        headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
        json={"url": url, "formats": ["markdown", "html"]},
        timeout=timeout,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return data.get("markdown", ""), data.get("html", "")
