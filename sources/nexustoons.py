import httpx
from urllib.parse import urljoin


class NexusToonsSource:
    """NexusToons adapter based on the current Keiyoushi/Tachiyomi source.

    Flow: /api/mangas -> /api/manga/{slug} -> /api/read/{chapter_id}.
    The API currently lives on nexustoons.com; nexustoons.site redirects there.
    """

    name = "NexusToons"
    base_url = "https://nexustoons.com"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": base_url + "/",
        "Origin": base_url,
    }
    timeout = httpx.Timeout(60.0, connect=20.0)

    async def _get_json(self, path, params=None):
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            http2=False,
        ) as client:
            r = await client.get(urljoin(self.base_url + "/", path.lstrip("/")), params=params)
            r.raise_for_status()
            try:
                return r.json()
            except Exception as e:
                snippet = (r.text or "")[:200].replace("\n", " ")
                raise RuntimeError(f"Resposta não-JSON da NexusToons: {snippet!r}") from e

    @staticmethod
    def _payload(data):
        # The source DTOs have changed shape across revisions; keep this
        # adapter tolerant while preserving the official endpoint flow.
        if not isinstance(data, dict):
            return {}
        payload = data.get("data")
        return payload if isinstance(payload, (dict, list)) else data

    @staticmethod
    def _title(item):
        if not isinstance(item, dict):
            return ""
        for key in ("title", "name", "displayName"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        title_obj = item.get("title")
        if isinstance(title_obj, dict):
            for key in ("pt-br", "pt", "romaji", "english", "native"):
                value = title_obj.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def _slug(item):
        if not isinstance(item, dict):
            return ""
        for key in ("slug", "mangaSlug"):
            value = item.get(key)
            if value:
                return str(value).strip().strip("/")
        url = item.get("url")
        if isinstance(url, str) and "/manga/" in url:
            return url.split("/manga/", 1)[1].strip("/")
        return ""

    async def search(self, query: str):
        query = (query or "").strip()
        if not query:
            return []

        data = await self._get_json(
            "/api/mangas",
            {
                "page": 1,
                "limit": 30,
                "includeNsfw": "true",
                "search": query,
                "sortBy": "updatedAt",
                "sortOrder": "desc",
                "categoryMode": "or",
            },
        )
        payload = self._payload(data)
        items = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
        # Normal response is {data:[...], page, pages}; tolerate {data:{items:[...]}} too.
        if isinstance(items, dict):
            items = items.get("items") or items.get("mangas") or items.get("works") or []

        out = []
        for item in items or []:
            title = self._title(item)
            slug = self._slug(item)
            if title and slug:
                out.append({"title": title, "url": f"{self.base_url}/manga/{slug}"})
        print(f"NexusToons | busca={query!r} | resultados={len(out)}")
        return out

    @staticmethod
    def _chapter_list(payload):
        if isinstance(payload, dict):
            chapters = payload.get("chapters")
            if isinstance(chapters, list):
                return chapters
            for key in ("data", "manga"):
                nested = payload.get(key)
                if isinstance(nested, dict) and isinstance(nested.get("chapters"), list):
                    return nested["chapters"]
        return []

    async def chapters(self, manga_url: str):
        slug = str(manga_url).split("/manga/", 1)[-1].strip("/")
        if not slug:
            return []
        data = await self._get_json(f"/api/manga/{slug}")
        payload = self._payload(data)
        if isinstance(payload, list):
            manga_data = {}
        else:
            manga_data = payload if isinstance(payload, dict) else {}
        chapters = self._chapter_list(manga_data)
        manga_title = self._title(manga_data) or "Manga"

        out = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            cid = ch.get("id") or ch.get("_id") or ch.get("chapterId")
            if not cid:
                continue
            number = ch.get("number") or ch.get("chapter") or ch.get("chapterNumber") or "?"
            name = ch.get("name") or ch.get("title") or f"Capítulo {number}"
            out.append({
                "name": str(name).strip(),
                "chapter_number": number,
                "url": str(cid),
                "manga_title": manga_title,
            })

        print(f"NexusToons | obra={slug} | capítulos={len(out)}")
        return out

    async def pages(self, chapter_id: str):
        chapter_id = str(chapter_id).strip()
        if not chapter_id:
            return []
        data = await self._get_json(f"/api/read/{chapter_id}")
        payload = self._payload(data)
        if not isinstance(payload, dict):
            return []

        pages = payload.get("pages") or []
        page_token = payload.get("pageToken") or payload.get("page_token")
        urls = []
        for index, page in enumerate(pages):
            if isinstance(page, str):
                url = page
            elif isinstance(page, dict):
                url = page.get("imageUrl") or page.get("image_url") or page.get("url")
            else:
                url = None
            if not url and page_token:
                url = f"{self.base_url}/api/p/{page_token}/{index}"
            if url:
                urls.append(url if str(url).startswith("http") else urljoin(self.base_url + "/", str(url).lstrip("/")))

        print(f"NexusToons | capítulo={chapter_id} | páginas={len(urls)}")
        return urls
