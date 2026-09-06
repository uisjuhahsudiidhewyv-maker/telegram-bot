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
# DONO DO BOTÃO
# ==========================================================

def is_owner(query):
    try:
        return query.from_user.id == int(query.data.split("|")[-1])
    except:
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
        DOWNLOAD_QUEUE.task_done()


async def send_chapter(job):

    async with DOWNLOAD_SEMAPHORE:

        message = job["message"]
        source = job["source"]
        chapter = job["chapter"]

        try:
            pages = await source.pages(chapter["url"])
        except Exception as e:
            print(f"Erro ao obter páginas ({source.__class__.__name__}): {type(e).__name__}: {e}")
            await message.reply_text("❌ Erro ao obter páginas.")
            return

        if not pages:
            await message.reply_text("❌ Nenhuma página encontrada.")
            return

        try:
            cbz_buffer, cbz_name = await create_cbz(
                pages,
                chapter.get("manga_title") or job.get("title") or "Manga",
                f"Cap_{chapter.get('chapter_number')}",
            )
        except Exception as e:
            print(f"Erro ao criar CBZ ({source.__class__.__name__}): {type(e).__name__}: {e}")
            await message.reply_text("❌ Erro ao criar CBZ.")
            return

        await message.reply_document(document=cbz_buffer, filename=cbz_name)
        cbz_buffer.close()


# ==========================================================
# BUSCAR EM TODAS AS FONTES (AGUARDANDO TODAS)
# ==========================================================

async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query_text = " ".join(context.args)
    if not query_text:
        await update.message.reply_text("Use /bb <nome>")
        return

    msg = await update.message.reply_text("🔎 Buscando em todas as fontes...")

    sources = get_all_sources()
    tasks = []

    for source_name, source in sources.items():
        tasks.append(search_source(source_name, source, query_text))

    results = await asyncio.gather(*tasks)

    combined = []
    for r in results:
        combined.extend(r)

    if not combined:
        await msg.edit_text("❌ Nenhum resultado encontrado.")
        return

    SEARCH_CACHE[msg.message_id] = combined

    await show_results(msg, update.effective_user.id, 0)


async def search_source(name, source, query):
    try:
        res = await source.search(query)
        return [
            {"source": name, "title": m["title"], "url": m["url"]}
            for m in res
        ]
    except:
        return []


# ==========================================================
# RESULTADOS PAGINADOS
# ==========================================================

async def show_results(message, user_id, page):

    data = SEARCH_CACHE[message.message_id]
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
        nav.append(InlineKeyboardButton("«", callback_data=f"page|{page-1}|{user_id}"))

    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"page|{page+1}|{user_id}"))

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
    total_pages = math.ceil(len(chapters) / CHAPTERS_PER_PAGE)

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
        nav.append(InlineKeyboardButton("«", callback_data=f"chap_page|{page-1}|{user_id}"))

    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"chap_page|{page+1}|{user_id}"))

    buttons.append(nav)

    buttons.append([
        InlineKeyboardButton("🔙 Voltar", callback_data=f"back|0|{user_id}")
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
    data = SEARCH_CACHE[query.message.message_id][index]

    source = get_all_sources()[data["source"]]
    chapters = await source.chapters(data["url"])

    context.user_data["chapters"] = chapters
    context.user_data["source"] = source
    context.user_data["title"] = data["title"]

    user_id = query.from_user.id

    buttons = [
        [InlineKeyboardButton("📥 Baixar tudo", callback_data=f"download_all|0|{user_id}")],
        [InlineKeyboardButton("📖 Ver capítulos", callback_data=f"chap_page|0|{user_id}")]
    ]

    await query.message.reply_text(
        f"📖 {data['title']}\nTotal: {len(chapters)} capítulos",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def download_all(update, context):
    query = update.callback_query
    await query.answer()
    if not is_owner(query):
        return

    chapters = context.user_data["chapters"]
    source = context.user_data["source"]

    for chap in chapters:
        await DOWNLOAD_QUEUE.put({
            "message": query.message,
            "source": source,
            "chapter": chap,
            "title": context.user_data.get("title") or "Manga"
        })

    await query.message.reply_text("📥 Todos capítulos adicionados na fila.")


async def download_one(update, context):
    query = update.callback_query
    await query.answer()
    if not is_owner(query):
        return

    index = int(query.data.split("|")[1])

    chap = context.user_data["chapters"][index]
    source = context.user_data["source"]

    await DOWNLOAD_QUEUE.put({
        "message": query.message,
        "source": source,
        "chapter": chap
    })

    await query.message.reply_text("📥 Capítulo adicionado na fila.")


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
    app.add_handler(CallbackQueryHandler(change_page, pattern="^page"))
    app.add_handler(CallbackQueryHandler(select_manga, pattern="^select"))
    app.add_handler(CallbackQueryHandler(download_all, pattern="^download_all"))
    app.add_handler(CallbackQueryHandler(download_one, pattern="^download_one"))
    app.add_handler(CallbackQueryHandler(change_chap_page, pattern="^chap_page"))
    app.add_handler(CallbackQueryHandler(back_to_results, pattern="^back"))

    async def startup(app):
        asyncio.create_task(worker())

    app.post_init = startup

    print("🤖 Bot iniciado")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
