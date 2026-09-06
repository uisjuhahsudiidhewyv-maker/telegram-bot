import httpx

class MangaDexSource:
    name = "MangaDex (PT-BR)"
    base_url = "https://mangadex.org"
    api = "https://api.mangadex.org"

    async def search(self, query):
        params = {
            "title": query,
            "limit": 100,
            "includes[]": "cover_art",
            "translatedLanguage[]": "pt-br",
            "contentRating[]": "safe",
            "contentRating[]": "suggestive",
            "contentRating[]": "erotica",
            "contentRating[]": "pornographic",
        }
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.api}/manga", params=params)
            r.raise_for_status()
            data = r.json()
        out=[]
        for m in data.get("data", []):
            attrs=m.get("attributes", {})
            titles=attrs.get("title", {}) or {}
            title=titles.get("pt-br") or titles.get("en") or next(iter(titles.values()), None)
            if title:
                out.append({"title": title, "url": m["id"]})
        return out

    async def chapters(self, manga_id):
        params={"manga[]": manga_id, "limit": 100, "translatedLanguage[]": "pt-br", "order[chapter]": "desc", "includeEmptyPages": 0}
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get(f"{self.api}/chapter", params=params); r.raise_for_status(); data=r.json()
        return [{"name": f"Capítulo {x.get('attributes',{}).get('chapter') or '?'}", "chapter_number": x.get('attributes',{}).get('chapter') or 0, "url": x['id'], "manga_title": "MangaDex"} for x in data.get('data', [])]

    async def pages(self, chapter_id):
        async with httpx.AsyncClient(timeout=30) as c:
            r=await c.get(f"{self.api}/at-home/server/{chapter_id}"); r.raise_for_status(); data=r.json()
        ch=data.get("chapter", {})
        base=data.get("baseUrl")
        h=ch.get("hash")
        return [f"{base}/data/{h}/{p}" for p in ch.get("data", [])]
