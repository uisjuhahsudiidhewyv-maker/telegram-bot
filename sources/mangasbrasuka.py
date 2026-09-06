import httpx
from bs4 import BeautifulSoup


class MangasBrasukaSource:
    name = "MangasBrasuka"
    base_url = "https://mangasbrasuka.com.br"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": base_url + "/",
    }

    async def _get(self, url, **kwargs):
        async with httpx.AsyncClient(headers=self.headers, timeout=40, follow_redirects=True) as c:
            r = await c.get(url, **kwargs)
            # Cloudflare/anti-bot cannot be solved reliably by a plain HTTP client on Railway.
            if r.status_code in (403, 429, 503):
                raise RuntimeError(f"MangasBrasuka bloqueou a requisição (HTTP {r.status_code})")
            r.raise_for_status()
            return r.text

    async def search(self, query):
        html = await self._get(self.base_url, params={"s": query})
        soup = BeautifulSoup(html, "html.parser")
        out, seen = [], set()
        # Aurora/Madara-style cards plus generic fallback.
        for a in soup.select('.page-item-detail .item-summary h3 a, .row.c-tabs-item__content .tab-summary .post-title a, a[href]'):
            href = a.get("href")
            title = a.get_text(" ", strip=True)
            if not href or not title or href in seen:
                continue
            if not any(k in href.lower() for k in ("manga", "manhwa", "manhua", "series")):
                continue
            seen.add(href)
            out.append({"title": title, "url": href})
        return out

    async def chapters(self, manga_url):
        html = await self._get(manga_url)
        soup = BeautifulSoup(html, "html.parser")
        import re
        title_el = soup.select_one("h1, .post-title h1")
        manga_title = title_el.get_text(" ", strip=True) if title_el else "MangasBrasuka"
        out, seen = [], set()
        for a in soup.select('.wp-manga-chapter a[href], .listing-chapters_wrap a[href], .chapter-list a[href], a[href]'):
            href = a.get("href")
            txt = a.get_text(" ", strip=True)
            if not href or href in seen:
                continue
            m = re.search(r"(?:cap(?:ítulo)?|chapter)\s*([0-9]+(?:[.,][0-9]+)?)", txt, re.I)
            if not m:
                continue
            seen.add(href)
            out.append({"name": txt, "chapter_number": m.group(1).replace(",", "."), "url": href, "manga_title": manga_title})
        return out

    async def pages(self, chapter_url):
        html = await self._get(chapter_url)
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for img in soup.select('.reading-content img, .page-break img, img'):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if src:
                out.append(src)
        return list(dict.fromkeys(out))
