"""Open museum APIs: The Met and the Art Institute of Chicago (no key, free).

Only public-domain artworks with an image are returned.
"""
from __future__ import annotations

from functools import lru_cache

import httpx

USER_AGENT = "festomuhely-asszisztens/0.1 (university project)"
MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects/{id}"
AIC_SEARCH = "https://api.artic.edu/api/v1/artworks/search"
AIC_IMAGE = "https://www.artic.edu/iiif/2/{image_id}/full/400,/0/default.jpg"
TIMEOUT = 12.0


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


@lru_cache(maxsize=128)
def search_met(query: str, max_results: int = 4) -> tuple[dict, ...]:
    out: list[dict] = []
    with _client() as c:
        r = c.get(MET_SEARCH, params={"q": query, "hasImages": "true", "limit": 25})
        r.raise_for_status()
        for oid in (r.json().get("objectIDs") or [])[:25]:
            if len(out) >= max_results:
                break
            o = c.get(MET_OBJECT.format(id=oid))
            if o.status_code != 200:
                continue
            d = o.json()
            if not (d.get("isPublicDomain") and d.get("primaryImageSmall")):
                continue
            out.append({
                "source": "The Met",
                "id": f"met-{oid}",
                "title": d.get("title") or "",
                "artist": d.get("artistDisplayName") or "unknown",
                "date": d.get("objectDate") or "",
                "medium": d.get("medium") or "",
                "url": d.get("objectURL") or "",
                "image_url": d["primaryImageSmall"],
            })
    return tuple(out)


@lru_cache(maxsize=128)
def search_aic(query: str, max_results: int = 4) -> tuple[dict, ...]:
    fields = "id,title,artist_display,date_display,medium_display,image_id,is_public_domain"
    with _client() as c:
        r = c.get(AIC_SEARCH, params={"q": query, "fields": fields, "limit": 20})
        r.raise_for_status()
        out = []
        for d in r.json().get("data", []):
            if len(out) >= max_results:
                break
            if not (d.get("is_public_domain") and d.get("image_id")):
                continue
            out.append({
                "source": "Art Institute of Chicago",
                "id": f"aic-{d['id']}",
                "title": d.get("title") or "",
                "artist": (d.get("artist_display") or "unknown").split("\n")[0],
                "date": d.get("date_display") or "",
                "medium": d.get("medium_display") or "",
                "url": f"https://www.artic.edu/artworks/{d['id']}",
                "image_url": AIC_IMAGE.format(image_id=d["image_id"]),
            })
    return tuple(out)


def search_museums(query: str, max_results: int = 4) -> list[dict]:
    """Searches both museums; if one is unreachable, continues with the other."""
    query = query.strip()[:120]
    max_results = max(1, min(int(max_results), 6))
    results: list[dict] = []
    errors: list[str] = []
    per_source = max(1, (max_results + 1) // 2)
    for name, fn in (("met", search_met), ("aic", search_aic)):
        try:
            results.extend(fn(query, per_source))
        except httpx.HTTPError as exc:
            errors.append(f"{name}: {type(exc).__name__}")
    if not results and errors:
        raise ConnectionError("The museum APIs are unreachable: " + ", ".join(errors))
    return results[:max_results]
