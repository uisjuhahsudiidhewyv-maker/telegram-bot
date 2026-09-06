import httpx, re, json
from bs4 import BeautifulSoup

class MangaBallSource:
    name="MangaBall (PT-BR)"
    base_url="https://mangaball.net"
    headers={"User-Agent":"Mozilla/5.0","Referer":base_url+"/"}

    async def search(self, query):
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as c:
            r=await c.post(f"{self.base_url}/api/v1/smart-search/search/", data={"search_input":query.strip()})
            r.raise_for_status(); data=r.json()
        out=[]
        for m in data.get("data",{}).get("manga",[]):
            title=m.get("title"); url=m.get("url")
            if title and url:
                out.append({"title":title,"url":url.rstrip('/').split('/')[-1]})
        return out

    async def chapters(self, manga_id):
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as c:
            r=await c.post(f"{self.base_url}/api/v1/chapter/chapter-listing-by-title-id/", data={"title_id":manga_id})
            r.raise_for_status(); data=r.json()
        out=[]
        for ch in data.get("chapters",[]):
            num=ch.get("number",0)
            for tr in ch.get("translations",[]):
                if tr.get("language") not in ("pt-br","pt"): continue
                out.append({"name":tr.get("name") or f"Cap. {num}","chapter_number":num,"url":tr.get("id"),"manga_title":"MangaBall"})
        return out

    async def pages(self, chapter_id):
        async with httpx.AsyncClient(headers=self.headers, timeout=30) as c:
            r=await c.get(f"{self.base_url}/chapter-detail/{chapter_id}/"); r.raise_for_status(); html=r.text
        soup=BeautifulSoup(html,"html.parser")
        script=';'.join(x.get_text() for x in soup.find_all('script'))
        m=re.search(r"const\s+chapterImages\s*=\s*JSON\.parse\(`([^`]+)`\)",script)
        if not m: return []
        try: return json.loads(m.group(1))
        except Exception: return []
