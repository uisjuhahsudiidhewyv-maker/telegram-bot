import httpx
from bs4 import BeautifulSoup

class MangaFireSource:
    name="MangaFire"
    base_url="https://mangafire.to"
    async def search(self,query):
        # HTML fallback: não depende do token VRF da API da MangaFire.
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"},timeout=30,follow_redirects=True) as c:
            r=await c.get(f"{self.base_url}/search",params={"keyword":query}); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser'); out=[]
        for card in soup.select('.manga-poster'):
            a=card.select_one('a[href]'); t=card.select_one('.manga-title')
            if a and t: out.append({'title':t.get_text(' ',strip=True),'url':a['href']})
        return out

    async def chapters(self,manga_url):
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"},timeout=30,follow_redirects=True) as c:
            r=await c.get(manga_url if manga_url.startswith('http') else self.base_url+manga_url); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser'); out=[]
        for a in soup.select('.chapters-list a[href]'):
            txt=a.get_text(' ',strip=True); import re
            m=re.search(r'(\d+(?:\.\d+)?)',txt)
            if m: out.append({'name':txt,'chapter_number':m.group(1),'url':a['href'],'manga_title':soup.select_one('h1').get_text(' ',strip=True) if soup.select_one('h1') else 'MangaFire'})
        return out

    async def pages(self,chapter_url):
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0","Referer":self.base_url+"/"},timeout=30,follow_redirects=True) as c:
            r=await c.get(chapter_url if chapter_url.startswith('http') else self.base_url+chapter_url); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        return [x.get('data-src') or x.get('src') for x in soup.select('.reader-area img[data-src], .reader-area img[src]') if x.get('data-src') or x.get('src')]
