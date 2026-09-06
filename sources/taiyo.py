import httpx, re, json
from bs4 import BeautifulSoup

class TaiyoSource:
    name="Taiyō (PT-BR)"
    base_url="https://taiyo.moe"
    imgcdn="https://cdn.taiyo.moe/medias"
    def __init__(self): self.token=None

    async def _token(self,c):
        if self.token:return self.token
        r=await c.get(self.base_url); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
        for s in soup.find_all('script',src=True):
            js=(await c.get(s['src'] if s['src'].startswith('http') else self.base_url+s['src'])).text
            m=re.search(r'NEXT_PUBLIC_MEILISEARCH_PUBLIC_KEY:\s*"([^"]+)"',js)
            if m:self.token=m.group(1); return self.token
        raise RuntimeError('Taiyō: token não encontrado')

    async def search(self, query):
        async with httpx.AsyncClient(timeout=40) as c:
            token=await self._token(c)
            body={"queries":[{"indexUid":"medias","q":query,"filter":["deletedAt IS NULL"],"limit":50,"offset":0}]}
            r=await c.post("https://meilisearch.taiyo.moe/multi-search",headers={"Authorization":f"Bearer {token}"},json=body)
            r.raise_for_status(); data=r.json()
        hits=(data.get("results") or [{}])[0].get("hits",[])
        out=[]
        for x in hits:
            titles=x.get("titles") or []
            title=next((t.get("title") for t in titles if 'pt' in str(t.get('language','')).lower()),None) or (titles[0].get('title') if titles else None)
            if title: out.append({"title":title,"url":str(x.get('id'))})
        return out

    async def chapters(self, manga_id):
        async with httpx.AsyncClient(timeout=40) as c:
            token=await self._token(c)
            url=f"{self.base_url}/api/trpc/chapters.getByMediaId?batch=1"
            inp=json.dumps({"0":{"json":{"mediaId":manga_id,"page":1,"perPage":100}}},separators=(',',':'))
            r=await c.get(url,params={"input":inp},headers={"Authorization":f"Bearer {token}"}); r.raise_for_status(); data=r.json()
        obj=data[0].get('result',{}).get('data',{}).get('json',{})
        out=[]
        for x in obj.get('chapters',[]):
            out.append({"name":x.get('title') or f"Capítulo {x.get('number')}","chapter_number":x.get('number',0),"url":f"{x.get('id')}/1","manga_title":"Taiyō"})
        return out

    async def pages(self, chapter_url):
        async with httpx.AsyncClient(timeout=40) as c:
            r=await c.get(f"{self.base_url}/chapter/{chapter_url}"); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
        # O capítulo atual contém os dados JSON em um script Next.js.
        text='\n'.join(s.get_text() for s in soup.find_all('script'))
        urls=re.findall(r'https://cdn\.taiyo\.moe/medias/[^"\\ ]+\.(?:jpg|jpeg|png|webp)',text)
        return list(dict.fromkeys(urls))
