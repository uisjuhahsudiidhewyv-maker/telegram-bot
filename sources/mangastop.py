import json
import re
import httpx
from bs4 import BeautifulSoup


class MangaStopSource:
    name = "Mangastop"
    base_url = "https://mangastop.net"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": base_url + "/",
    }

    async def search(self, query):
        async with httpx.AsyncClient(headers=self.headers, timeout=40, follow_redirects=True) as c:
            r = await c.get(self.base_url, params={"s": query})
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out, seen = [], set()
        # MangaThemesia search cards.
        selectors = [
            ".c-tabs-item__content",
            ".row.c-tabs-item__content",
            ".tab-summary",
            ".list-update_item",
        ]
        for selector in selectors:
            for card in soup.select(selector):
                a = card.select_one('a[href]')
                if not a:
                    continue
                title_el = card.select_one('.post-title a, .tab-summary .post-title, .tab-summary .post-title a, h3 a, h4 a')
                title = (title_el or a).get_text(" ", strip=True)
                href = a.get("href")
                if title and href and href not in seen:
                    seen.add(href)
                    out.append({"title": title, "url": href})
            if out:
                break
        return out

    async def chapters(self, manga_url):
        async with httpx.AsyncClient(headers=self.headers, timeout=40, follow_redirects=True) as c:
            r = await c.get(manga_url if manga_url.startswith("http") else self.base_url + manga_url)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        title_el = soup.select_one("h1, .post-title h1")
        manga_title = title_el.get_text(" ", strip=True) if title_el else "Mangastop"
        out, seen = [], set()
        for a in soup.select(".chapter-list a[href], .listing-chapters_wrap a[href], .wp-manga-chapter a[href], a[href]"):
            txt = a.get_text(" ", strip=True)
            href = a.get("href")
            if not href or href in seen:
                continue
            m = re.search(r"(?:cap(?:ítulo)?|chapter)\s*([0-9]+(?:[.,][0-9]+)?)", txt, re.I)
            if not m:
                continue
            seen.add(href)
            out.append({"name": txt, "chapter_number": m.group(1).replace(",", "."), "url": href, "manga_title": manga_title})
        return out

    async def pages(self, chapter_url):
        async with httpx.AsyncClient(headers=self.headers, timeout=40, follow_redirects=True) as c:
            r = await c.get(chapter_url)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        urls = []
        for img in soup.select(".reading-content img, .page-break img, img"):
            src = img.get("data-src") or img.get("data-lazy-src") or img.get("src")
            if src and "mihon" not in src.lower():
                urls.append(src)
        if urls:
            return list(dict.fromkeys(urls))
        # MangaThemesia fallback: JSON array embedded in the page.
        text = str(soup)
        m = re.search(r"(?:var\s+images|chapterImages|image_list)\s*=\s*(\[[^;]+\])", text, re.S | re.I)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        return []
