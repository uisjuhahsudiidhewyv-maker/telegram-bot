from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource
from sources.mangalivreblog import MangaLivreBlogSource
from sources.wolftoon import WolftoonSource
from sources.mangaball import MangaBallSource
from sources.mangadex import MangaDexSource
from sources.mangafire import MangaFireSource
from sources.mangastop import MangaStopSource
from sources.mangasbrasuka import MangasBrasukaSource
from sources.taiyo import TaiyoSource

_sources = {
    "ToonBr": ToonBrSource(),
    "MangaFlix": MangaFlixSource(),
    "MangaLivreBlog": MangaLivreBlogSource(),
    "Wolftoon": WolftoonSource(),
    "MangaBall (PT-BR)": MangaBallSource(),
    "MangaDex (PT-BR)": MangaDexSource(),
    "MangaFire": MangaFireSource(),
    "Mangastop": MangaStopSource(),
    "MangasBrasuka": MangasBrasukaSource(),
    "Taiyō (PT-BR)": TaiyoSource(),
}

def get_all_sources():
    return _sources
