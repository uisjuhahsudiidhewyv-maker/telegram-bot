import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36"

async def resolve_cover_url(source, item):
    """Resolve a cover without persisting the image on the Railway server."""
    if item.get("cover"):
        return item["cover"]

    cover_method = getattr(source, "cover", None)
    if cover_method:
        try:
            result = await cover_method(item.get("url"))
            if result:
                return result
        except Exception:
            pass

    # MangaDex has a stable API/cover CDN and is handled using the same logic
    # as the original Manga-Bot project.
    if source.__class__.__name__ == "MangaDexCodeflixSource":
        try:
            data = await source._get_json(f"/manga/{item['url']}", {"includes[]": "cover_art"})
            card = (data.get("data") or {})
            rels = card.get("relationships") or []
            cover = next((x for x in rels if x.get("type") == "cover_art"), None)
            filename = ((cover or {}).get("attributes") or {}).get("fileName")
            if filename:
                return f"https://uploads.mangadex.org/covers/{item['url']}/{filename}.512.jpg"
        except Exception:
            pass

    # For sources returning a real manga URL, use the site's og:image/twitter:image.
    url = str(item.get("url") or "")
    if url.startswith(("http://", "https://")):
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": UA}) as client:
                r = await client.get(url)
                r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for selector in (("meta", {"property": "og:image"}), ("meta", {"name": "twitter:image"})):
                tag = soup.find(*selector)
                if tag and tag.get("content"):
                    return urljoin(str(r.url), tag["content"])
            img = soup.find("img")
            if img and img.get("src"):
                return urljoin(str(r.url), img["src"])
        except Exception:
            pass
    return None
