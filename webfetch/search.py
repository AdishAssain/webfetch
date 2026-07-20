from __future__ import annotations

import httpx

from .config import EXA_API_KEY, EXA_SEARCH_URL, TAVILY_API_KEY, TAVILY_SEARCH_URL


def discover(
    query: str,
    *,
    n: int = 10,
    search_type: str = "auto",
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    provider: str | None = None,
    timeout: float = 60.0,
) -> list[dict]:
    """Search for candidate URLs. Auto-picks Exa, else Tavily, by which key is set.

    search_type (Exa): auto | fast | instant | deep-lite | deep | deep-reasoning.
    Returns [{url, title, text}] where text is query-relevant highlights.
    """
    provider = provider or ("exa" if EXA_API_KEY else "tavily" if TAVILY_API_KEY else "")
    if provider == "exa":
        return _exa(query, n, search_type, include_domains, exclude_domains, timeout)
    if provider == "tavily":
        return _tavily(query, n, include_domains, exclude_domains, timeout)
    raise RuntimeError("Set EXA_API_KEY or TAVILY_API_KEY to use discover().")


def _exa(query, n, search_type, include_domains, exclude_domains, timeout) -> list[dict]:
    payload = {
        "query": query,
        "type": search_type,
        "numResults": n,
        "contents": {"highlights": True},
    }
    if include_domains:
        payload["includeDomains"] = include_domains
    if exclude_domains:
        payload["excludeDomains"] = exclude_domains
    resp = httpx.post(
        EXA_SEARCH_URL, headers={"x-api-key": EXA_API_KEY}, json=payload, timeout=timeout
    )
    resp.raise_for_status()
    results = []
    for r in resp.json().get("results", []):
        highlights = r.get("highlights") or []
        results.append(
            {
                "url": r["url"],
                "title": r.get("title", ""),
                "text": "\n".join(highlights) or r.get("text", ""),
            }
        )
    return results


def _tavily(query, n, include_domains, exclude_domains, timeout) -> list[dict]:
    payload = {"query": query, "max_results": n}
    if include_domains:
        payload["include_domains"] = include_domains
    if exclude_domains:
        payload["exclude_domains"] = exclude_domains
    resp = httpx.post(
        TAVILY_SEARCH_URL,
        headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return [
        {"url": r["url"], "title": r.get("title", ""), "text": r.get("content", "")}
        for r in resp.json().get("results", [])
    ]
