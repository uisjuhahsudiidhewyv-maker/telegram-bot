import asyncio
from urllib.parse import quote
import httpx


class MangaDexCodeflixSource:
    name = "MangaDex (PT-BR)"
    api = "https://api.mangadex.org"
    headers = {"User-Agent": "MangaBot/1.0 (compatible; Codeflix logic)"}
    timeout = httpx.Timeout(30.0, connect=15.0)

    async def _get_json(self, path, params=None):
        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
            r = await client.get(f"{self.api}{path}", params=params)
            r.raise_for_status()
            return r.json()

    async def search(self, query: str):
        if not query.strip():
            return []
        params = [
            ("limit", 20),
            ("offset", 0),
            ("includes[]", "cover_art"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"),
            ("title", query.strip()),
            ("order[relevance]", "desc"),
        ]
        data = await self._get_json("/manga", params)
        results = []
        for card in data.get("data", []):
            attrs = card.get("attributes", {})
            titles = attrs.get("title") or {}
            title = titles.get("pt-br") or titles.get("en") or next(iter(titles.values()), None)
            if title:
                results.append({"title": title, "url": card["id"]})
        return results

    async def chapters(self, manga_id: str):
        params = [
            ("limit", 500),
            ("offset", 0),
            ("translatedLanguage[]", "pt-br"),
            ("includes[]", "scanlation_group"),
            ("includes[]", "user"),
            ("order[volume]", "desc"),
            ("order[chapter]", "desc"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"),
            ("contentRating[]", "pornographic"),
        ]
        data = await self._get_json(f"/manga/{manga_id}/feed", params)
        chapters = []
        visited = set()
        for item in data.get("data", []):
            attrs = item.get("attributes", {})
            number = attrs.get("chapter")
            if number in visited:
                continue
            visited.add(number)
            title = attrs.get("title") or ""
            display = f"{number} - {title}" if title else str(number or "")
            chapters.append({
                "name": display,
                "chapter_number": number or "0",
                "url": item.get("id"),
                "manga_title": "",
            })
        return chapters

    async def pages(self, chapter_id: str):
        data = await self._get_json(f"/at-home/server/{chapter_id}", {"forcePort443": "false"})
        if data.get("result") == "error":
            return []
        base = data.get("baseUrl")
        chapter = data.get("chapter") or {}
        chapter_hash = chapter.get("hash")
        files = chapter.get("data") or []
        if not base or not chapter_hash:
            return []
        return [f"{base}/data/{chapter_hash}/{name}" for name in files if name]
