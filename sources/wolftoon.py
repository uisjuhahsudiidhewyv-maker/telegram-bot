import asyncio
import httpx

class WolftoonSource:
    def __init__(self):
        self.base_url = "https://wolftoon.lovable.app"
        self.supabase_url = "https://encmakrlmutvsdzpodov.supabase.co"
        self.api_key = None
        self.client = httpx.AsyncClient(timeout=30)

    async def get_api_key(self):
        if self.api_key:
            return self.api_key
        # pegar script para extrair api_key
        r = await self.client.get(self.base_url)
        import re
        match = re.search(r'src=["\']?(/assets/index-[^"\'>]+\.js)["\']?', r.text)
        if not match:
            raise Exception("Script não encontrado")
        script_url = f"{self.base_url}{match.group(1)}"
        script = await self.client.get(script_url)
        match_key = re.search(r'supabase\.co[\'"],\s*[a-zA-Z0-9_$]+\s*=\s*[\'"](eyJ[^\'"]+)', script.text)
        if not match_key:
            raise Exception("API Key não encontrada")
        self.api_key = match_key.group(1)
        return self.api_key

    async def search(self, query):
        api_key = await self.get_api_key()
        params = {"select": "*", "order": "rating.desc", "apikey": api_key}
        r = await self.client.get(f"{self.supabase_url}/rest/v1/titles", params=params)
        data = r.json()
        results = []
        # Pesquisa SOMENTE pelo título. A sinopse não participa do filtro.
        query_norm = query.strip().lower()
        for manga in data:
            title = str(manga.get("title") or "").strip()
            if title and query_norm in title.lower():
                results.append({
                    "title": title,
                    "url": manga["id"],  # usar ID para buscar capítulos
                    "manga_title": title
                })
        return results

    async def chapters(self, manga_id):
        api_key = await self.get_api_key()
        params = {"select": "id,title_id,chapter_number,created_at", "title_id": f"eq.{manga_id}", "order": "chapter_number.desc", "apikey": api_key}
        r = await self.client.get(f"{self.supabase_url}/rest/v1/chapters", params=params)
        data = r.json()
        chapters = []
        for ch in data:
            chapters.append({
                "chapter_number": ch["chapter_number"],
                "url": ch["id"],
                "manga_title": "",  # opcional
                "name": ch.get("title", "")
            })
        return chapters

    async def pages(self, chapter_id):
        api_key = await self.get_api_key()
        params = {"select": "id,title_id,images", "id": f"eq.{chapter_id}", "apikey": api_key}
        r = await self.client.get(f"{self.supabase_url}/rest/v1/chapters", params=params)
        data = r.json()
        if not data:
            return []
        return data[0].get("images", [])
