from urllib.parse import quote_plus, urljoin
import httpx
from bs4 import BeautifulSoup


class NineMangaCodeflixSource:
    name = "NineManga Brasil"
    base_url = "https://br.ninemanga.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
    }
    timeout = httpx.Timeout(30.0, connect=15.0)

    async def _get(self, url):
        async with httpx.AsyncClient(headers=self.headers, timeout=self.timeout, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r

    async def search(self, query: str):
        url = urljoin(self.base_url, f"search/?wd={quote_plus(query)}")
        r = await self._get(url)
        soup = BeautifulSoup(r.content, "html.parser")
        container = soup.find("ul", class_="direlist")
        if not container:
            return []
        results = []
        for card in container.find_all("li"):
            a = card.find("a", class_="bookname")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = urljoin(self.base_url, a.get("href", ""))
            if title and href:
                results.append({"title": title, "url": href})
        return results

    async def chapters(self, manga_url: str):
        url = f"{manga_url}?waring=1"
        r = await self._get(url)
        soup = BeautifulSoup(r.content, "html.parser")
        container = soup.find("div", class_="chapterbox")
        if not container:
            return []
        results = []
        for li in container.find_all("li"):
            a = li.find("a")
            if not a:
                continue
            href = urljoin(self.base_url, a.get("href", ""))
            name = (a.get("title") or a.get_text(strip=True)).strip()
            results.append({
                "name": name,
                "chapter_number": name,
                "url": href,
                "manga_title": "",
            })
        return results

    async def pages(self, chapter_url: str):
        r = await self._get(chapter_url)
        soup = BeautifulSoup(r.content, "html.parser")
        container = soup.find("select", id="page")
        if not container:
            return []
        total = len(container.find_all("option"))
        if total <= 0:
            return []
        # Mantém a lógica do projeto Codeflix: o site agrupa 10 páginas por URL.
        count = 10
        pages = (total - 1) // count
        images = []
        base = str(r.url)
        if base.endswith(".html"):
            base = base[:-5]
        for page in range(pages):
            page_url = f"{base}-{count}-{page + 1}.html"
            try:
                pr = await self._get(page_url)
            except Exception:
                continue
            psoup = BeautifulSoup(pr.content, "html.parser")
            for img in psoup.find_all("img", class_="manga_pic"):
                src = img.get("src")
                if src:
                    images.append(urljoin(str(pr.url), src))
        return images
