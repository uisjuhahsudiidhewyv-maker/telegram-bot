from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource
from sources.mangalivreblog import MangaLivreBlogSource
from sources.wolftoon import WolftoonSource
from sources.codeflix_mangadex import MangaDexCodeflixSource
from sources.codeflix_ninemanga import NineMangaCodeflixSource

_sources = {
    "ToonBr": ToonBrSource(),
    "MangaFlix": MangaFlixSource(),
    "MangaLivreBlog": MangaLivreBlogSource(),
    "Wolftoon": WolftoonSource(),
    "MangaDex (PT-BR)": MangaDexCodeflixSource(),
    "NineManga Brasil": NineMangaCodeflixSource(),
}


def get_all_sources():
    return _sources
