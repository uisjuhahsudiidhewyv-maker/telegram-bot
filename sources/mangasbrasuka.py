import httpx
from bs4 import BeautifulSoup

class MangasBrasukaSource:
    name="MangasBrasuka"
    base_url="https://mangasbrasuka.com.br"
    async def search(self,query):
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"},timeout=30,follow_redirects=True) as c:
            r=await c.get(self.base_url,params={"s":query}); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser'); out=[]; seen=set()
        for a in soup.select('a[href]'):
            href=a.get('href',''); title=a.get_text(' ',strip=True)
            if title and href and href not in seen and any(k in href.lower() for k in ('manga','manhwa','manhua')):
                seen.add(href); out.append({'title':title,'url':href})
        return out
    async def chapters(self,manga_url):
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"},timeout=30,follow_redirects=True) as c:
            r=await c.get(manga_url); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser'); import re; out=[]
        for a in soup.select('a[href]'):
            txt=a.get_text(' ',strip=True); m=re.search(r'(?:cap(?:ítulo)?|chapter)\s*([0-9]+(?:\.[0-9]+)?)',txt,re.I)
            if m: out.append({'name':txt,'chapter_number':m.group(1),'url':a['href'],'manga_title':soup.select_one('h1').get_text(' ',strip=True) if soup.select_one('h1') else 'MangasBrasuka'})
        return out
    async def pages(self,chapter_url):
        async with httpx.AsyncClient(headers={"User-Agent":"Mozilla/5.0"},timeout=30,follow_redirects=True) as c:
            r=await c.get(chapter_url); r.raise_for_status()
        soup=BeautifulSoup(r.text,'html.parser')
        return [x.get('data-src') or x.get('src') for x in soup.select('img[data-src],img[src]') if x.get('data-src') or x.get('src')]
