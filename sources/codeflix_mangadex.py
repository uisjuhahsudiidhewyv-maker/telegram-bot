import json
from urllib.parse import quote
import httpx


class MangaDexSource:
    """Adapted from Codeflix-Bots/Manga-Bot plugins/mangadex.py."""
    name = "MangaDex (PT-BR)"
    api = "https://api.mangadex.org"
    covers = "https://uploads.mangadex.org/covers"
    headers = {"User-Agent": "MangaBot/Codeflix-compatible"}

    async def _get(self, url, params=None):
        async with httpx.AsyncClient(headers=self.headers, timeout=60, follow_redirects=True) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()

    async def search(self, query: str):
        params = [
            ("limit", 20), ("offset", 0), ("includes[]", "cover_art"),
            ("includes[]", "author"), ("includes[]", "artist"),
            ("contentRating[]", "safe"), ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"), ("title", query), ("order[relevance]", "desc")
        ]
        data = await self._get(f"{self.api}/manga", params=params)
        results = []
        for card in data.get("data", []):
            attrs = card.get("attributes", {})
            titles = attrs.get("title", {}) or {}
            # Prefer Brazilian Portuguese, then English, then any title.
            title = titles.get("pt-br") or titles.get("pt_br") or titles.get("en") or next(iter(titles.values()), None)
            if not title:
                continue
            cover = ""
            for rel in card.get("relationships", []):
                if rel.get("type") == "cover_art":
                    fn = (rel.get("attributes") or {}).get("fileName")
                    if fn:
                        cover = f"{self.covers}/{card['id']}/{fn}.512.jpg"
                    break
            results.append({"title": title, "url": card["id"], "picture_url": cover})
        return results

    async def chapters(self, manga_id: str):
        params = [
            ("limit", 500), ("offset", 0), ("includes[]", "scanlation_group"),
            ("includes[]", "user"), ("order[volume]", "desc"), ("order[chapter]", "desc"),
            ("contentRating[]", "safe"), ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"), ("contentRating[]", "pornographic"),
            ("translatedLanguage[]", "pt-br"), ("translatedLanguage[]", "pt")
        ]
        data = await self._get(f"{self.api}/manga/{manga_id}/feed", params=params)
        chapters, visited = [], set()
        for ch in data.get("data", []):
            attrs = ch.get("attributes", {})
            number = attrs.get("chapter")
            # Same deduplication principle used by Codeflix.
            key = str(number) if number is not None else ch.get("id")
            if key in visited:
                continue
            visited.add(key)
            label = str(number or "0")
            if attrs.get("title"):
                label += " - " + attrs["title"]
            chapters.append({
                "name": label,
                "chapter_number": number or "0",
                "url": ch["id"],
                "manga_title": "",
            })
        return chapters

    async def pages(self, chapter_id: str):
        data = await self._get(f"{self.api}/at-home/server/{chapter_id}", params={"forcePort443": "false"})
        if data.get("result") == "error":
            return []
        base = data.get("baseUrl")
        chapter = data.get("chapter") or {}
        h = chapter.get("hash")
        files = chapter.get("data") or []
        if not base or not h:
            return []
        return [f"{base}/data/{h}/{name}" for name in files]
