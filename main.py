import os
import asyncio
import logging
import math

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO)

DOWNLOAD_QUEUE = asyncio.Queue()
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)

SEARCH_CACHE = {}
RESULTS_PER_PAGE = 10
CHAPTERS_PER_PAGE = 15

# ==========================================================
# LIMPEZA DE RASTROS
# ==========================================================
# O bot apaga mensagens de comando e mensagens de controle
# que ele próprio enviou. Os arquivos CBZ enviados continuam
# no grupo, pois são o conteúdo desejado.
DELETE_BOT_TRACES = os.getenv("DELETE_BOT_TRACES", "true").lower() in (
    "1", "true", "yes", "on"
)
TRACE_DELETE_DELAY = int(os.getenv("TRACE_DELETE_DELAY", "300"))

# {(chat_id, thread_id, user_id): {message_id, ...}}
CONTROL_MESSAGES = {}


def _session_key(message, user_id):
    chat_id = message.chat_id
    thread_id = getattr(message, "message_thread_id", None) or 0
    return (chat_id, thread_id, user_id)


def _remember_control(message, user_id, bot):
    if not DELETE_BOT_TRACES:
        return

    key = _session_key(message, user_id)
    CONTROL_MESSAGES.setdefault(key, set()).add(message.message_id)

    # Evita deixar um menu abandonado para sempre.
    asyncio.create_task(
        _expire_control_message(key, message.message_id, bot)
    )


async def _expire_control_message(key, message_id, bot):
    await asyncio.sleep(max(0, TRACE_DELETE_DELAY))

    ids = CONTROL_MESSAGES.get(key)
    if not ids or message_id not in ids:
        return

    chat_id, _, _ = key

    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id
        )
    except Exception:
        pass

    ids.discard(message_id)
    if not ids:
        CONTROL_MESSAGES.pop(key, None)


async def track_and_send(bot, chat_id, user_id, text, **kwargs):
    """Envia uma mensagem de controle e registra-a para limpeza."""
    message = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    _remember_control(message, user_id, bot)
    return message


async def forget_control(message, user_id):
    if not DELETE_BOT_TRACES or not message:
        return

    key = _session_key(message, user_id)
    ids = CONTROL_MESSAGES.get(key)
    if ids:
        ids.discard(message.message_id)
        if not ids:
            CONTROL_MESSAGES.pop(key, None)

    try:
        await message.delete()
    except Exception:
        # O bot pode não ter permissão para apagar mensagens.
        pass


async def cleanup_session(bot, message, user_id):
    """Apaga todos os controles registrados para este usuário/tópico."""
    if not DELETE_BOT_TRACES or not message:
        return

    key = _session_key(message, user_id)
    ids = list(CONTROL_MESSAGES.pop(key, set()))

    for message_id in ids:
        try:
            await bot.delete_message(
                chat_id=message.chat_id,
                message_id=message_id
            )
        except Exception:
            pass


async def delete_user_command(update):
    """Apaga o comando do administrador (/bb ...), se possível."""
    if not DELETE_BOT_TRACES or not update.message:
        return

    try:
        await update.message.delete()
    except Exception:
        pass


# ==========================================================
# DONO DO BOTÃO
# ==========================================================

def is_owner(query):
    try:
        return query.from_user.id == int(query.data.split("|")[-1])
    except Exception:
        return False


# ==========================================================
# WORKER
# ==========================================================

async def worker():
    while True:
        job = await DOWNLOAD_QUEUE.get()
        try:
            await send_chapter(job)
        except Exception as e:
            print("Erro worker:", e)
        finally:
            DOWNLOAD_QUEUE.task_done()


async def send_chapter(job):
    async with DOWNLOAD_SEMAPHORE:
        message = job["message"]
        bot = job["bot"]
        source = job["source"]
        chapter = job["chapter"]
        chat_id = job["chat_id"]
        thread_id = job.get("thread_id")

        try:
            pages = await source.pages(chapter["url"])
        except Exception:
            try:
                status = await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Erro ao obter páginas.",
                    message_thread_id=thread_id
                )
                await asyncio.sleep(2)
                await forget_control(status, job["user_id"])
            except Exception:
                pass
            return

        if not pages:
            try:
                status = await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Nenhuma página encontrada.",
                    message_thread_id=thread_id
                )
                await asyncio.sleep(2)
                await forget_control(status, job["user_id"])
            except Exception:
                pass
            return

        try:
            # Algumas fontes (principalmente leitores/CDNs) exigem Referer.
            chapter_url = str(chapter.get("url") or "")
            referer = chapter_url if chapter_url.startswith("http") else None
            image_headers = {"User-Agent": "Mozilla/5.0"}
            if source.__class__.__name__ == "TaiyoSource":
                image_headers["Referer"] = "https://taiyo.moe/"
            elif referer:
                image_headers["Referer"] = referer

            cbz_buffer, cbz_name = await create_cbz(
                pages,
                chapter.get("manga_title", "Manga"),
                f"Cap_{chapter.get('chapter_number')}",
                image_headers=image_headers,
            )
        except Exception:
            try:
                status = await bot.send_message(
                    chat_id=chat_id,
                    text="❌ Erro ao criar CBZ.",
                    message_thread_id=thread_id
                )
                await asyncio.sleep(2)
                await forget_control(status, job["user_id"])
            except Exception:
                pass
            return

        try:
            # O CBZ NÃO é apagado: ele é o conteúdo que o bot deve entregar.
            await bot.send_document(
                chat_id=chat_id,
                document=cbz_buffer,
                filename=cbz_name,
                message_thread_id=thread_id
            )
        finally:
            cbz_buffer.close()


# ==========================================================
# BUSCAR EM TODAS AS FONTES
# ==========================================================

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Apaga imediatamente o comando /bb nome.
    await delete_user_command(update)

    query_text = " ".join(context.args)
    if not query_text:
        # Sem a mensagem original, não há necessidade de deixar aviso.
        return

    user_id = update.effective_user.id
    bot = context.bot

    msg = await track_and_send(
        bot,
        update.effective_chat.id,
        user_id,
        "🔎 Buscando em todas as fontes..."
    )

    sources = get_all_sources()
    tasks = [
        search_source(source_name, source, query_text)
        for source_name, source in sources.items()
    ]

    results = await asyncio.gather(*tasks)

    # Junta os resultados de TODAS as fontes.
    # A filtragem é feita exclusivamente pelo título pesquisado.
    combined = []
    seen = set()

    for source_results in results:
        for item in source_results:
            # Evita duplicatas da mesma obra dentro da mesma fonte.
            key = (
                item["source"],
                _normalize_search_text(item["title"]),
                str(item["url"])
            )
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)

    # Ordenação previsível: título e depois fonte.
    combined.sort(key=lambda x: (
        _normalize_search_text(x["title"]),
        _normalize_search_text(x["source"])
    ))

    if not combined:
        await msg.edit_text("❌ Nenhum resultado encontrado.")
        # Some sozinho depois do prazo configurado, se continuar abandonado.
        return

    SEARCH_CACHE[msg.message_id] = combined
    await show_results(msg, user_id, 0)


def _normalize_search_text(text):
    """Normaliza o texto apenas para comparação da pesquisa."""
    import re
    import unicodedata

    text = str(text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches_search(title, query):
    """
    O filtro final usa SOMENTE o título do mangá.

    Todas as palavras pesquisadas precisam aparecer no título. Isso evita
    resultados que uma fonte encontrou apenas por sinopse, descrição, autor,
    etc. Ex.: 'solo leveling' só aceita títulos que contenham 'solo' e
    'leveling'.
    """
    title_norm = _normalize_search_text(title)
    query_words = _normalize_search_text(query).split()

    if not title_norm or not query_words:
        return False

    return all(word in title_norm for word in query_words)


async def search_source(name, source, query):
    try:
        res = await source.search(query) or []
        filtered = []

        for manga in res:
            title = str(manga.get("title") or "").strip()
            url = manga.get("url")

            # O resultado só entra se o TÍTULO realmente corresponder
            # à pesquisa. Não usamos sinopse, autor ou descrição.
            if not title or not url or not _matches_search(title, query):
                continue

            filtered.append({
                "source": name,
                "title": title,
                "url": url
            })

        return filtered
    except Exception as e:
        print(f"[{name}] erro na busca: {e}")
        return []


# ==========================================================
# RESULTADOS PAGINADOS
# ==========================================================

async def show_results(message, user_id, page):
    data = SEARCH_CACHE.get(message.message_id, [])
    if not data:
        return

    total_pages = math.ceil(len(data) / RESULTS_PER_PAGE)
    start = page * RESULTS_PER_PAGE
    end = start + RESULTS_PER_PAGE

    buttons = []

    for i, item in enumerate(data[start:end], start=start):
        buttons.append([
            InlineKeyboardButton(
                f"{item['title']} ({item['source']})",
                callback_data=f"select|{i}|{user_id}"
            )
        ])

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "«",
                callback_data=f"page|{page-1}|{user_id}"
            )
        )

    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "»",
                callback_data=f"page|{page+1}|{user_id}"
            )
        )

    if nav:
        buttons.append(nav)

    await message.edit_text(
        f"📚 Resultados ({page+1}/{total_pages})",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==========================================================
# CAPÍTULOS PAGINADOS
# ==========================================================

async def show_chapters(message, context, page, user_id):
    chapters = context.user_data["chapters"]
    total_pages = max(1, math.ceil(len(chapters) / CHAPTERS_PER_PAGE))

    start = page * CHAPTERS_PER_PAGE
    end = start + CHAPTERS_PER_PAGE

    buttons = []

    for i, chap in enumerate(chapters[start:end], start=start):
        buttons.append([
            InlineKeyboardButton(
                f"Cap {chap.get('chapter_number')}",
                callback_data=f"download_one|{i}|{user_id}"
            )
        ])

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "«",
                callback_data=f"chap_page|{page-1}|{user_id}"
            )
        )

    if page < total_pages - 1:
        nav.append(
            InlineKeyboardButton(
                "»",
                callback_data=f"chap_page|{page+1}|{user_id}"
            )
        )

    if nav:
        buttons.append(nav)

    buttons.append([
        InlineKeyboardButton(
            "🔙 Voltar",
            callback_data=f"back|0|{user_id}"
        )
    ])

    await message.edit_text(
        f"📖 Capítulos ({page+1}/{total_pages})",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ==========================================================
# CALLBACKS
# ==========================================================

async def change_page(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    page = int(query.data.split("|")[1])
    await show_results(query.message, query.from_user.id, page)


async def select_manga(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    index = int(query.data.split("|")[1])
    data = SEARCH_CACHE.get(query.message.message_id, [])[index]

    # O mesmo card/menu é reutilizado, evitando criar outra mensagem.
    source = get_all_sources()[data["source"]]

    try:
        chapters = await source.chapters(data["url"])
    except Exception:
        await cleanup_session(context.bot, query.message, query.from_user.id)
        return

    context.user_data["chapters"] = chapters
    context.user_data["source"] = source
    context.user_data["title"] = data["title"]

    user_id = query.from_user.id

    buttons = [
        [
            InlineKeyboardButton(
                "📥 Baixar tudo",
                callback_data=f"download_all|0|{user_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "📖 Ver capítulos",
                callback_data=f"chap_page|0|{user_id}"
            )
        ]
    ]

    await query.message.edit_text(
        f"📖 {data['title']}\nTotal: {len(chapters)} capítulos",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def download_all(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    chapters = context.user_data.get("chapters", [])
    source = context.user_data.get("source")

    if not chapters or not source:
        await cleanup_session(context.bot, query.message, query.from_user.id)
        return

    for chap in chapters:
        await DOWNLOAD_QUEUE.put({
            "message": query.message,
            "bot": context.bot,
            "chat_id": query.message.chat_id,
            "thread_id": getattr(query.message, "message_thread_id", None),
            "source": source,
            "chapter": chap,
            "user_id": query.from_user.id
        })

    # Apaga o menu e a sessão de controle.
    await cleanup_session(context.bot, query.message, query.from_user.id)


async def download_one(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    index = int(query.data.split("|")[1])

    chapters = context.user_data.get("chapters", [])
    source = context.user_data.get("source")

    if index >= len(chapters) or not source:
        await cleanup_session(context.bot, query.message, query.from_user.id)
        return

    chap = chapters[index]

    await DOWNLOAD_QUEUE.put({
        "message": query.message,
        "bot": context.bot,
        "chat_id": query.message.chat_id,
        "thread_id": getattr(query.message, "message_thread_id", None),
        "source": source,
        "chapter": chap,
        "user_id": query.from_user.id
    })

    # O menu desaparece assim que o pedido é feito.
    await cleanup_session(context.bot, query.message, query.from_user.id)


async def change_chap_page(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    page = int(query.data.split("|")[1])
    await show_chapters(query.message, context, page, query.from_user.id)


async def back_to_results(update, context):
    query = update.callback_query
    await query.answer()

    if not is_owner(query):
        return

    await show_results(query.message, query.from_user.id, 0)


# ==========================================================
# MAIN
# ==========================================================

def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    app.add_handler(CommandHandler("bb", buscar))
    app.add_handler(CallbackQueryHandler(change_page, pattern=r"^page"))
    app.add_handler(CallbackQueryHandler(select_manga, pattern=r"^select"))
    app.add_handler(CallbackQueryHandler(download_all, pattern=r"^download_all"))
    app.add_handler(CallbackQueryHandler(download_one, pattern=r"^download_one"))
    app.add_handler(CallbackQueryHandler(change_chap_page, pattern=r"^chap_page"))
    app.add_handler(CallbackQueryHandler(back_to_results, pattern=r"^back"))

    async def startup(application):
        asyncio.create_task(worker())

    app.post_init = startup

    print("🤖 Bot iniciado")
    print(f"🧹 Limpeza de rastros: {'ATIVADA' if DELETE_BOT_TRACES else 'DESATIVADA'}")

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
