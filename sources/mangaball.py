import httpx
import re
import json
from bs4 import BeautifulSoup


class MangaBallSource:
    name = "MangaBall (PT-BR)"
    base_url = "https://mangaball.net"

    def _headers(self, csrf=None):
        h = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
            "Referer": self.base_url + "/",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/plain, */*",
        }
        if csrf:
            h["X-CSRF-TOKEN"] = csrf
        return h

    async def _csrf(self, client):
        r = await client.get(self.base_url, headers=self._headers())
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.select_one('meta[name="csrf-token"]')
        if meta and meta.get("content"):
            return meta["content"]
        # Fallback for pages that expose the token in inline JS.
        m = re.search(r'(?:csrf-token|csrfToken)["\']?\s*[:=]\s*["\']([^"\']+)', r.text, re.I)
        return m.group(1) if m else None

    async def search(self, query):
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            csrf = await self._csrf(c)
            r = await c.post(
                f"{self.base_url}/api/v1/smart-search/search/",
                headers=self._headers(csrf),
                data={"search_input": query.strip()},
            )
            if r.status_code == 403 and csrf:
                csrf = await self._csrf(c)
                r = await c.post(
                    f"{self.base_url}/api/v1/smart-search/search/",
                    headers=self._headers(csrf),
                    data={"search_input": query.strip()},
                )
            r.raise_for_status()
            data = r.json()

        out = []
        for m in data.get("data", {}).get("manga", []):
            title = m.get("title")
            url = m.get("url")
            if title and url:
                # The official source stores the slug in /title-detail/<slug>/.
                parts = url.rstrip("/").split("/")
                slug = parts[-1] if parts else url
                out.append({"title": title, "url": slug})
        return out

    async def chapters(self, manga_id):
        async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
            csrf = await self._csrf(c)
            r = await c.post(
                f"{self.base_url}/api/v1/chapter/chapter-listing-by-title-id/",
                headers=self._headers(csrf),
                data={"title_id": manga_id},
            )
            if r.status_code == 403:
                csrf = await self._csrf(c)
                r = await c.post(
                    f"{self.base_url}/api/v1/chapter/chapter-listing-by-title-id/",
                    headers=self._headers(csrf),
                    data={"title_id": manga_id},
                )
            r.raise_for_status()
            data = r.json()

        out = []
        for ch in data.get("chapters", []):
            num = ch.get("number", 0)
            for tr in ch.get("translations", []):
                lang = str(tr.get("language") or "").lower()
                if lang not in ("pt-br", "pt-pt", "pt"):
                    continue
                cid = tr.get("id")
                if not cid:
                    continue
                out.append({
                    "name": tr.get("name") or f"Cap. {num}",
                    "chapter_number": num,
                    "url": cid,
                    "manga_title": "MangaBall",
                })
        return out

    async def pages(self, chapter_id):
        async with httpx.AsyncClient(
            headers=self._headers(), timeout=40, follow_redirects=True
        ) as c:
            r = await c.get(f"{self.base_url}/chapter-detail/{chapter_id}/")
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")

        # This is the same reader payload used by the original source.
        script = ";".join(x.get_text() if not x.string else x.string for x in soup.find_all("script"))
        m = re.search(r"const\s+chapterImages\s*=\s*JSON\.parse\(`([^`]+)`\)", script)
        if not m:
            # Some deployments expose the array directly.
            m = re.search(r"chapterImages\s*=\s*(\[[^;]+\])", script, re.S)
        if not m:
            return []
        raw = m.group(1)
        try:
            return json.loads(raw)
        except Exception:
            try:
                return json.loads(bytes(raw, "utf-8").decode("unicode_escape"))
            except Exception:
                return []
