import json
import re
import httpx
from bs4 import BeautifulSoup

class MangaBallSource:
    name='MangaBall (PT-BR)'
    base='https://mangaball.net'
    headers={
        'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36',
        'Accept':'*/*','Accept-Language':'pt-BR,pt;q=0.9,en;q=0.8',
        'X-Requested-With':'XMLHttpRequest','Referer':base+'/'
    }
    async def _client(self):
        c=httpx.AsyncClient(timeout=45,headers=self.headers,follow_redirects=True)
        r=await c.get(self.base+'/')
        soup=BeautifulSoup(r.text,'html.parser')
        token=soup.select_one('meta[name="csrf-token"]')
        if token and token.get('content'):
            c.headers['X-CSRF-TOKEN']=token['content']
        return c
    @staticmethod
    def _abs(base,url):
        if not url:return ''
        if url.startswith('//'):return 'https:'+url
        if url.startswith('/'):return base+url
        return url
    async def search(self,q):
        c=await self._client()
        try:
            r=await c.post(self.base+'/api/v1/smart-search/search/',data={'search_input':q.strip()})
            r.raise_for_status(); d=r.json()
            items=((d.get('data') or {}).get('manga') or [])
            out=[]
            for x in items:
                title=x.get('title') or x.get('name')
                url=x.get('url')
                if title and url:
                    out.append({'title':title,'url':self._abs(self.base,url)})
            return out
        finally: await c.aclose()
    async def chapters(self,url):
        c=await self._client()
        try:
            # The source's current extension derives title_id from the final URL slug.
            slug=str(url).rstrip('/').split('/')[-1]
            title_id=slug.rsplit('-',1)[-1]
            if not title_id or not title_id.isdigit():
                title_id=slug
            r=await c.post(self.base+'/api/v1/chapter/chapter-listing-by-title-id/',data={'title_id':title_id})
            r.raise_for_status(); d=r.json()
            groups=d.get('chapters') or d.get('ALL_CHAPTERS') or (d.get('data') or {}).get('chapters') or (d.get('data') or {}).get('ALL_CHAPTERS') or []
            out=[]
            for ch in groups:
                num=ch.get('number') or ch.get('number_float') or ch.get('chapter') or '0'
                for tr in ch.get('translations') or []:
                    lang=str(tr.get('language') or '').lower()
                    if lang not in ('pt-br','pt','pt_pt','pt-pt'): continue
                    cid=tr.get('id') or tr.get('url')
                    if not cid: continue
                    out.append({'chapter_number':num,'name':tr.get('name') or f'Capítulo {num}','url':cid})
            # Fallback when the API returns a flat chapter list.
            if not out:
                for ch in groups:
                    cid=ch.get('id') or ch.get('url')
                    if cid: out.append({'chapter_number':ch.get('number') or ch.get('chapter') or '0','name':ch.get('title') or ch.get('name') or 'Capítulo','url':cid})
            return sorted(out,key=lambda x: float(str(x.get('chapter_number','0')).replace(',','.').split('-')[0]) if re.match(r'^\d+(?:[.,]\d+)?',str(x.get('chapter_number','0'))) else 0, reverse=True)
        finally: await c.aclose()
    async def pages(self,chapter_url):
        if not str(chapter_url).startswith('http'):
            chapter_url=self.base+'/chapter-detail/'+str(chapter_url).strip('/')+'/'
        c=await self._client()
        try:
            r=await c.get(chapter_url); r.raise_for_status()
            soup=BeautifulSoup(r.text,'html.parser')
            scripts='\n'.join(s.get_text() for s in soup.find_all('script'))
            m=re.search(r'const\s+chapterImages\s*=\s*JSON\.parse\(`([^`]+)`\)',scripts)
            if m:
                raw=m.group(1).replace('\\`','`')
                try:
                    arr=json.loads(raw)
                    return [self._abs(self.base,x) for x in arr if isinstance(x,str)]
                except Exception: pass
            # Generic fallback for direct image arrays/DOM images.
            for pattern in [r'chapterImages\s*=\s*(\[[^;]+\])',r'"chapterImages"\s*:\s*(\[[^]]+\])']:
                m=re.search(pattern,scripts,re.S)
                if m:
                    try:
                        arr=json.loads(m.group(1)); return [self._abs(self.base,x) for x in arr if isinstance(x,str)]
                    except Exception: pass
            return [self._abs(self.base,img.get('data-src') or img.get('src')) for img in soup.select('img') if (img.get('data-src') or img.get('src')) and not 'logo' in (img.get('src') or '').lower()]
        finally: await c.aclose()
