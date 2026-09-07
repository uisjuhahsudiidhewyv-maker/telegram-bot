import asyncio
import re
import zipfile
from io import BytesIO
from urllib.parse import urlparse

import httpx


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


def _headers_for(url: str):
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}" if p.scheme and p.netloc else ""
    return {
        "User-Agent": UA,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Referer": origin + "/" if origin else "https://www.google.com/",
    }


async def download_image(client, url):
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if not url.startswith(("http://", "https://")):
        print(f"URL de imagem inválida: {url}")
        return None

    try:
        r = await client.get(url, headers=_headers_for(url), timeout=60, follow_redirects=True)
        r.raise_for_status()
        content_type = (r.headers.get("content-type") or "").lower()
        data = r.content
        # Aceita imagens mesmo quando o servidor não informa Content-Type corretamente,
        # mas rejeita respostas HTML/JSON que são páginas de erro.
        if "text/html" in content_type or "application/json" in content_type:
            print(f"Resposta não é imagem ({r.status_code}): {url}")
            return None
        if not data:
            return None
        return data
    except Exception as e:
        print(f"Erro ao baixar imagem {url}: {type(e).__name__}: {e}")
        return None


def _safe(value, fallback="Manga"):
    value = str(value or fallback)
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value).strip("._")
    return value or fallback


async def create_cbz(image_urls, manga_title, chapter_name):
    image_urls = [u for u in (image_urls or []) if isinstance(u, str) and u.strip()]
    if not image_urls:
        raise Exception("Nenhuma URL de imagem foi fornecida pela fonte")

    cbz_filename = f"{_safe(chapter_name, 'Capitulo')}.cbz"

    limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, limits=limits) as client:
        tasks = [download_image(client, url) for url in image_urls]
        images = await asyncio.gather(*tasks)

    images = [img for img in images if img]
    if not images:
        raise Exception(f"Nenhuma das {len(image_urls)} imagens pôde ser baixada")

    cbz_buffer = BytesIO()
    with zipfile.ZipFile(cbz_buffer, "w", compression=zipfile.ZIP_DEFLATED) as cbz:
        for i, img_bytes in enumerate(images, start=1):
            cbz.writestr(f"{i:03d}.jpg", img_bytes)

    cbz_buffer.seek(0)
    return cbz_buffer, cbz_filename
