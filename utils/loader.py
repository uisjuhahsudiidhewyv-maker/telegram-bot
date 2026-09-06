from sources.toonbr import ToonBrSource
from sources.mangaflix import MangaFlixSource
from sources.mangalivreblog import MangaLivreBlogSource
from sources.wolftoon import WolftoonSource
from sources.mangadex import MangaDexSource
from sources.mangaball import MangaBallSource
from sources.taiyo import TaiyoSource

_sources={
 "ToonBr":ToonBrSource(), "MangaFlix":MangaFlixSource(), "MangaLivreBlog":MangaLivreBlogSource(), "Wolftoon":WolftoonSource(),
 "MangaBall (PT-BR)":MangaBallSource(), "MangaDex (PT-BR)":MangaDexSource(), "Taiyō (PT-BR)":TaiyoSource(),
}
def get_all_sources(): return _sources
