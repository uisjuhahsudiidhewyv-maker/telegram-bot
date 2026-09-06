import httpx
import re
import json
from bs4 import BeautifulSoup


class TaiyoSource:
    name = "Taiyō (PT-BR)"
    base_url = "https://taiyo.moe"
    imgcdn = "https://cdn.taiyo.moe/medias"

    def __init__(self):
        self.token = None

    def _headers(self, token=None):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Referer": self.base_url + "/",
        }
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    async def _token(self, c):
        if self.token:
            return self.token
        r = await c.get(self.base_url, headers=self._headers())
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        scripts = soup.find_all("script", src=True)
        for s in reversed(scripts):
            src = s["src"]
            if not src.startswith("http"):
                src = self.base_url + src
            try:
                js = (await c.get(src, headers=self._headers())).text
            except Exception:
                continue
            m = re.search(r'NEXT_PUBLIC_MEILISEARCH_PUBLIC_KEY:\s*"([^"]+)"', js)
            if m:
                self.token = m.group(1)
                return self.token
        raise RuntimeError("Taiyō: token não encontrado")

    async def search(self, query):
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            token = await self._token(c)
            body = {"queries": [{"indexUid": "medias", "q": query, "filter": ["deletedAt IS NULL"], "limit": 50, "offset": 0}]}
            r = await c.post(
                "https://meilisearch.taiyo.moe/multi-search",
                headers=self._headers(token),
                json=body,
            )
            r.raise_for_status()
            data = r.json()
        hits = (data.get("results") or [{}])[0].get("hits", [])
        out = []
        for x in hits:
            titles = x.get("titles") or []
            title = next((t.get("title") for t in titles if "pt" in str(t.get("language", "")).lower()), None)
            title = title or (titles[0].get("title") if titles else None)
            if title and x.get("id"):
                out.append({"title": title, "url": str(x["id"])})
        return out

    async def chapters(self, manga_id):
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            token = await self._token(c)
            url = f"{self.base_url}/api/trpc/chapters.getByMediaId?batch=1"
            inp = json.dumps({"0": {"json": {"mediaId": manga_id, "page": 1, "perPage": 100}}}, separators=(",", ":"))
            r = await c.get(url, params={"input": inp}, headers=self._headers(token))
            r.raise_for_status()
            data = r.json()
        obj = data[0].get("result", {}).get("data", {}).get("json", {})
        out = []
        for x in obj.get("chapters", []):
            cid = x.get("id")
            if not cid:
                continue
            out.append({
                "name": x.get("title") or f"Capítulo {x.get('number')}",
                "chapter_number": x.get("number", 0),
                "url": f"{cid}/1",
                "manga_title": "Taiyō",
            })
        return out

    @staticmethod
    def _extract_media_chapter(html):
        # Taiyō is Next.js and the reader payload is embedded/escaped in an RSC script.
        soup = BeautifulSoup(html, "html.parser")
        for script in soup.find_all("script"):
            text = script.string or script.get_text()
            if not text or "mediaChapter" not in text:
                continue
            # Mirror the parser used by the source: take the object after mediaChapter,
            # stop before the chapters property, then unescape JSON.
            marker = r'\"mediaChapter\":'
            pos = text.find(marker)
            if pos < 0:
                marker = '"mediaChapter":'
                pos = text.find(marker)
                if pos < 0:
                    continue
            start = pos + len(marker)
            tail = text[start:]
            # Find the next escaped chapters field; this avoids greedy matching across RSC chunks.
            end_candidates = [tail.find(r',\"chapters\":'), tail.find(',"chapters":')]
            end = min([x for x in end_candidates if x >= 0], default=-1)
            if end >= 0:
                raw = tail[:end] + "}"
            else:
                raw = tail
            raw = raw.replace('\\"', '"').replace('\\\\', '\\')
            try:
                return json.loads(raw)
            except Exception:
                # Fallback: find a balanced JSON object starting at the marker.
                depth = 0
                in_str = False
                esc = False
                for i, ch in enumerate(raw):
                    if in_str:
                        if esc:
                            esc = False
                        elif ch == "\\":
                            esc = True
                        elif ch == '"':
                            in_str = False
                    else:
                        if ch == '"':
                            in_str = True
                        elif ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1
                            if depth == 0:
                                try:
                                    return json.loads(raw[: i + 1])
                                except Exception:
                                    break
        return None

    async def pages(self, chapter_url):
        # The chapter URL is /chapter/<chapter-id>/1. The page contains the
        # mediaChapter object; pages are served as /medias/<media-id>/chapters/<chapter-id>/<page-id>.jpg
        clean = str(chapter_url).strip().strip("/")
        if clean.startswith("http"):
            url = clean
        else:
            url = f"{self.base_url}/chapter/{clean}"

        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            r = await c.get(url, headers=self._headers())
            r.raise_for_status()
            obj = self._extract_media_chapter(r.text)

        if not obj:
            return []
        media = obj.get("media") or {}
        media_id = media.get("id")
        chapter_id = obj.get("id")
        pages = obj.get("pages") or []
        if not media_id or not chapter_id:
            return []
        return [
            f"{self.imgcdn}/{media_id}/chapters/{chapter_id}/{p.get('id')}.jpg"
            for p in pages
            if p.get("id")
        ]
