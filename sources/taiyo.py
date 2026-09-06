import json,re,httpx
from bs4 import BeautifulSoup

class TaiyoSource:
    name='Taiyō (PT-BR)'; base='https://taiyo.moe'; imgcdn='https://cdn.taiyo.moe/medias'
    def __init__(self): self.token=''
    async def _token(self,c):
        if self.token:return self.token
        html=(await c.get(self.base)).text; soup=BeautifulSoup(html,'html.parser')
        scripts=[]
        for s in soup.select('script[src]'):
            u=s.get('src'); scripts.append(u if u.startswith('http') else self.base+u)
        for u in reversed(scripts):
            try:
                t=(await c.get(u)).text
                m=re.search(r'NEXT_PUBLIC_MEILISEARCH_PUBLIC_KEY:\s*"([^"]+)"',t)
                if m: self.token=m.group(1); return self.token
            except Exception: pass
        # Sometimes the token is present in the page payload itself.
        m=re.search(r'NEXT_PUBLIC_MEILISEARCH_PUBLIC_KEY.{0,10}["\']([^"\']+)',html)
        if m:self.token=m.group(1);return self.token
        raise RuntimeError('Token Taiyō não encontrado')
    async def search(self,q):
        async with httpx.AsyncClient(timeout=45,headers={'User-Agent':'Mozilla/5.0'}) as c:
            tok=await self._token(c)
            body={'queries':[{'indexUid':'medias','q':q,'filter':['deletedAt IS NULL'],'limit':21,'offset':0}]}
            r=await c.post('https://meilisearch.taiyo.moe/multi-search',headers={'Authorization':f'Bearer {tok}'},json=body); r.raise_for_status(); d=r.json()
        hits=(d.get('results') or [{}])[0].get('hits',[]); out=[]
        for x in hits:
            titles=x.get('titles') or []
            title=next((t.get('title') for t in titles if 'pt' in str(t.get('language','')).lower()),None) or next((t.get('title') for t in titles if t.get('title')),None)
            if title and x.get('id'): out.append({'title':title,'url':x['id']})
        return out
    async def chapters(self,mid):
        async with httpx.AsyncClient(timeout=45,headers={'User-Agent':'Mozilla/5.0'}) as c:
            page=1; out=[]
            while True:
                inp={'0':{'json':{'mediaId':mid,'page':page,'perPage':50}}}
                # tRPC response is a JSON array; the actual payload is nested under result.data.json.
                r=await c.get(f'{self.base}/api/trpc/chapters.getByMediaId',params={'batch':'1','input':json.dumps(inp,separators=(',',':'))}); r.raise_for_status(); raw=r.text
                m=re.search(r'"json":(\{"chapters".*?\})\s*\}',raw)
                if not m: break
                try: d=json.loads(m.group(1))
                except Exception: break
                rows=d.get('chapters') or []; out.extend(rows)
                if page>=int(d.get('totalPages') or page) or not rows: break
                page+=1
        return [{'chapter_number':x.get('number'),'name':x.get('title') or f"Capítulo {x.get('number')}",'url':f"{self.base}/chapter/{x.get('id')}/1"} for x in sorted(out,key=lambda x: float(x.get('number') or 0),reverse=True) if x.get('id')]
    async def pages(self,chapter_url):
        async with httpx.AsyncClient(timeout=45,headers={'User-Agent':'Mozilla/5.0'}) as c:
            r=await c.get(chapter_url); r.raise_for_status(); soup=BeautifulSoup(r.text,'html.parser')
        scripts='\n'.join(s.get_text() for s in soup.find_all('script'))
        # Mirror the extension's mediaChapter extraction without depending on a fragile HTML selector.
        marker='\\"mediaChapter\\":'
        idx=scripts.find(marker)
        if idx<0: idx=scripts.find('"mediaChapter":')
        if idx<0:return []
        start=scripts.find('{',idx)
        if start<0:return []
        depth=0; end=-1; quoted=False; esc=False
        for i in range(start,len(scripts)):
            ch=scripts[i]
            if quoted:
                if esc: esc=False
                elif ch=='\\': esc=True
                elif ch=='"': quoted=False
                continue
            if ch=='"': quoted=True
            elif ch=='{': depth+=1
            elif ch=='}':
                depth-=1
                if depth==0: end=i+1; break
        if end<0:return []
        raw=scripts[start:end].replace('\\"','"').replace('\\\\','\\')
        try:d=json.loads(raw)
        except Exception:return []
        media=(d.get('media') or {}).get('id'); cid=d.get('id')
        if not media or not cid:return []
        return [f'{self.imgcdn}/{media}/chapters/{cid}/{p.get("id")}.jpg' for p in d.get('pages',[]) if p.get('id')]
