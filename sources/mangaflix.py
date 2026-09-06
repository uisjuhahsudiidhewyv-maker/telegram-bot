import httpx


class MangaFlixSource:
    """MangaFlix adapter baseado na implementação oficial da extensão Tachiyomi/Keiyoushi."""

    name = "MangaFlix"
    base_url = "https://mangaflix.net"
    api_url = "https://api.mangaflix.net/v1"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Origin": base_url,
        "Referer": base_url + "/",
    }

    timeout = httpx.Timeout(60.0, connect=20.0)

    async def _get_json(self, path, params=None):
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            http2=False,
        ) as client:
            response = await client.get(f"{self.api_url}{path}", params=params)
            response.raise_for_status()
            return response.json()

    # ================= SEARCH =================
    async def search(self, query: str):
        query = (query or "").strip()
        if not query:
            return []

        # A API do MangaFlix retorna os resultados em data.works.
        data = await self._get_json(
            "/search/mangas",
            {"query": query, "selected_language": "pt-br"},
        )

        payload = data.get("data") or {}
        works = payload.get("works") or []

        results = []
        for item in works:
            manga_id = item.get("_id")
            title = (item.get("name") or "").strip()
            if manga_id and title:
                results.append({
                    "title": title,
                    "url": manga_id,
                })

        print(f"MangaFlix | busca={query!r} | resultados={len(results)}")
        return results

    # ================= CHAPTERS =================
    async def chapters(self, manga_id: str):
        manga_id = str(manga_id).strip()
        if not manga_id:
            return []

        data = await self._get_json(f"/mangas/{manga_id}")
        manga_data = data.get("data") or {}
        manga_title = manga_data.get("name") or "Manga"

        chapters = []
        for chapter in manga_data.get("chapters") or []:
            chapter_id = chapter.get("_id")
            number = chapter.get("number")
            if not chapter_id:
                continue

            name = chapter.get("name")
            display_name = (name or "").strip() or f"Capítulo {number}"
            chapters.append({
                "name": display_name,
                "chapter_number": number,
                "url": chapter_id,
                "manga_title": manga_title,
            })

        return chapters

    # ================= PAGES =================
    async def pages(self, chapter_id: str):
        chapter_id = str(chapter_id).strip()
        if not chapter_id:
            return []

        data = await self._get_json(
            f"/chapters/{chapter_id}",
            {"selected_language": "pt-br"},
        )

        chapter_data = data.get("data") or {}
        images = chapter_data.get("images") or []

        urls = []
        for image in images:
            url = image.get("default_url") if isinstance(image, dict) else None
            if url:
                urls.append(url)

        print(f"MangaFlix | capítulo={chapter_id} | páginas={len(urls)}")
        return urls
