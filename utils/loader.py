from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource
from sources.mangalivreblog import MangaLivreBlogSource
from sources.wolftoon import WolftoonSource
from sources.codeflix_ninemanga import NineMangaSource
from sources.codeflix_mangadex import MangaDexSource

_sources = {
    "ToonBr": ToonBrSource(),
    "MangaFlix": MangaFlixSource(),
    "MangaLivreBlog": MangaLivreBlogSource(),
    "Wolftoon": WolftoonSource(),
    "NineManga": NineMangaSource(),
    "MangaDex (PT-BR)": MangaDexSource(),
}

def get_all_sources():
    return _sources
