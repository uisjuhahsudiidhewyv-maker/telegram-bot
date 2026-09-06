import httpx


class MangaDexSource:
    name = "MangaDex (PT-BR)"
    api = "https://api.mangadex.org"

    async def search(self, query):
        params = [
            ("title", query),
            ("limit", "100"),
            ("translatedLanguage[]", "pt-br"),
            ("contentRating[]", "safe"),
            ("contentRating[]", "suggestive"),
            ("contentRating[]", "erotica"),
            ("includes[]", "cover_art"),
        ]
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            r = await c.get(f"{self.api}/manga", params=params)
            r.raise_for_status()
            data = r.json()
        out = []
        for m in data.get("data", []):
            attrs = m.get("attributes", {})
            titles = attrs.get("title", {}) or {}
            title = titles.get("pt-br") or titles.get("pt") or titles.get("en") or next(iter(titles.values()), None)
            if title:
                out.append({"title": title, "url": m["id"]})
        return out

    async def chapters(self, manga_id):
        params = [
            ("manga[]", manga_id),
            ("limit", "500"),
            ("translatedLanguage[]", "pt-br"),
            ("order[chapter]", "desc"),
            ("order[volume]", "desc"),
            ("includeEmptyPages", "0"),
        ]
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            r = await c.get(f"{self.api}/chapter", params=params)
            r.raise_for_status()
            data = r.json()
        out = []
        for x in data.get("data", []):
            attrs = x.get("attributes", {})
            # Chapters hosted externally have no downloadable page list; skip them.
            if attrs.get("externalUrl"):
                continue
            num = attrs.get("chapter") or "?"
            out.append({
                "name": attrs.get("title") or f"Capítulo {num}",
                "chapter_number": num,
                "url": x["id"],
                "manga_title": "MangaDex",
            })
        return out

    async def pages(self, chapter_id):
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            r = await c.get(f"{self.api}/at-home/server/{chapter_id}")
            r.raise_for_status()
            data = r.json()
        ch = data.get("chapter", {})
        base = data.get("baseUrl")
        h = ch.get("hash")
        if not base or not h:
            return []
        # Prefer normal images and fall back to data-saver when the normal list is empty.
        names = ch.get("data") or ch.get("dataSaver") or []
        if not names:
            return []
        folder = "data" if ch.get("data") else "data-saver"
        return [f"{base}/{folder}/{h}/{p}" for p in names]
