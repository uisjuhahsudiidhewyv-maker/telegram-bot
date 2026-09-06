from typing import List
from urllib.parse import urlparse, urljoin, quote_plus
import httpx
from bs4 import BeautifulSoup


class NineMangaSource:
    """Adapted from Codeflix-Bots/Manga-Bot plugins/ninemanga.py."""
    name = "NineManga"
    base_url = "https://www.ninemanga.com/"
    search_url = urljoin(base_url, "search/")
    query_param = "waring=1"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
        "Accept-Language": "en-US,en;q=0.5",
    }

    async def _get(self, url):
        async with httpx.AsyncClient(headers=self.headers, timeout=60, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r

    def _soup(self, content):
        return BeautifulSoup(content, "html.parser")

    async def search(self, query: str):
        r = await self._get(self.search_url + "?wd=" + quote_plus(query))
        bs = self._soup(r.content)
        container = bs.find("ul", {"class": "direlist"})
        if not container:
            return []
        results = []
        for card in container.find_all("li"):
            a = card.find("a", {"class": "bookname"})
            img = card.find("img")
            if not a or not a.get("href"):
                continue
            results.append({
                "title": a.get_text(" ", strip=True).title(),
                "url": urljoin(self.base_url, a["href"]),
                "picture_url": urljoin(self.base_url, img.get("src")) if img and img.get("src") else "",
            })
        return results

    async def chapters(self, manga_url: str):
        url = manga_url + ("&" if "?" in manga_url else "?") + self.query_param
        r = await self._get(url)
        bs = self._soup(r.content)
        container = bs.find("div", {"class": "chapterbox"})
        if not container:
            return []
        chapters = []
        for li in container.find_all("li"):
            a = li.find("a")
            if not a or not a.get("href"):
                continue
            title = (a.get("title") or a.get_text(" ", strip=True) or "Capítulo").strip()
            chapters.append({
                "name": title,
                "chapter_number": self._chapter_number(title),
                "url": urljoin(self.base_url, a["href"]),
                "manga_title": "",
            })
        return chapters

    @staticmethod
    def _chapter_number(text):
        import re
        m = re.search(r"\d+(?:\.\d+)?", text or "")
        return m.group(0) if m else "0"

    async def pages(self, chapter_url: str):
        # Mirrors the Codeflix strategy: inspect the page selector and request
        # the paginated chapter pages where the site exposes them.
        r = await self._get(chapter_url)
        bs = self._soup(r.content)
        container = bs.find("select", {"id": "page"})
        options = container.find_all("option") if container else []

        images = [
            urljoin(str(r.url), img.get("src"))
            for img in bs.find_all("img", {"class": "manga_pic"})
            if img.get("src")
        ]

        count = 10
        total = len(options)
        page_count = (total - 1) // count if total else 0
        chapter_str = str(r.url)
        if chapter_str.endswith(".html"):
            chapter_base = chapter_str[:-5]
            for page in range(page_count):
                url = f"{chapter_base}-{count}-{page + 1}.html"
                try:
                    pr = await self._get(url)
                    pbs = self._soup(pr.content)
                    images.extend(
                        urljoin(str(pr.url), img.get("src"))
                        for img in pbs.find_all("img", {"class": "manga_pic"})
                        if img.get("src")
                    )
                except Exception as e:
                    print(f"[NineManga] página adicional falhou: {e}")

        # preserve order and remove duplicates
        out, seen = [], set()
        for u in images:
            if u and u not in seen:
                seen.add(u); out.append(u)
        return out
