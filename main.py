import asyncio
import logging
import math
import os
import re
import time
import unicodedata
from collections import defaultdict
from uuid import uuid4

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

from auth import authorized
from utils.loader import get_all_sources
from utils.cbz import create_cbz

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("mangabot")

DOWNLOAD_QUEUE = asyncio.Queue()
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
SESSIONS = {}
SEARCH_LOCKS = defaultdict(asyncio.Lock)
SEARCH_TASKS = {}
SEARCH_MESSAGES = {}
RESULTS_PER_PAGE = 10
CHAPTERS_PER_PAGE = 15
TEMP_ERROR_SECONDS = 5
SESSION_TTL = 600
ACTIVE_BATCHES = {}


def norm(text):
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", text).strip()


def title_matches(title, query):
    t = norm(title)
    words = [w for w in re.findall(r"[\w]+", norm(query)) if w]
    return bool(words) and all(w in t for w in words)


def owner_ok(query):
    try:
        return int(query.data.split("|")[-1]) == query.from_user.id
    except Exception:
        return False


async def safe_delete(message):
    if not message:
        return False
    for attempt in range(3):
        try:
            await message.delete()
            return True
        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(0.4)
            else:
                log.debug("Não foi possível apagar mensagem %s: %s", getattr(message, "message_id", "?"), e)
    return False


async def temp_error(bot, chat_id, text, thread_id=None):
    try:
        msg = await bot.send_message(chat_id, text, message_thread_id=thread_id)
        await asyncio.sleep(TEMP_ERROR_SECONDS)
        await safe_delete(msg)
    except Exception:
        pass


async def search_one(name, source, query):
    try:
        async with asyncio.timeout(35):
            raw = await source.search(query)
        valid = []
        for item in raw or []:
            title = str(item.get("title") or "").strip()
            url = item.get("url")
            # Busca Global filtra somente pelo título.
            if title and url and title_matches(title, query):
                valid.append({"source": name, "title": title, "url": url})
        log.info("Busca | %-22s | OK | %d resultados", name, len(valid))
        return valid
    except Exception as e:
        log.warning("Busca | %-22s | ERRO | %s", name, e)
        return []


def dedupe(items):
    seen = set()
    out = []
    for item in items:
        key = (item["source"].lower(), str(item["url"]).lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


async def show_results(message, user_id, page):
    session = SESSIONS.get((message.chat_id, user_id))
    if not session:
        return
    data = session["results"]
    total_pages = max(1, math.ceil(len(data) / RESULTS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * RESULTS_PER_PAGE
    buttons = []
    for i, item in enumerate(data[start:start + RESULTS_PER_PAGE], start=start):
        label = f"{item['title']} ({item['source']})"
        buttons.append([InlineKeyboardButton(label[:64], callback_data=f"select|{i}|{user_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("«", callback_data=f"page|{page-1}|{user_id}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"page|{page+1}|{user_id}"))
    if nav:
        buttons.append(nav)
    await message.edit_text(f"📚 Resultados ({page+1}/{total_pages})", reply_markup=InlineKeyboardMarkup(buttons))


async def show_chapters(message, user_id, page=0):
    session = SESSIONS.get((message.chat_id, user_id))
    if not session or not session.get("chapters"):
        return
    chapters = session["chapters"]
    total_pages = max(1, math.ceil(len(chapters) / CHAPTERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))
    start = page * CHAPTERS_PER_PAGE
    buttons = []
    for i, chap in enumerate(chapters[start:start + CHAPTERS_PER_PAGE], start=start):
        label = str(chap.get("name") or chap.get("chapter_number") or f"Cap {i+1}")
        buttons.append([InlineKeyboardButton(label[:64], callback_data=f"download_one|{i}|{user_id}")])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("«", callback_data=f"chap_page|{page-1}|{user_id}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("»", callback_data=f"chap_page|{page+1}|{user_id}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data=f"back|0|{user_id}")])
    await message.edit_text(f"📖 Capítulos ({page+1}/{total_pages})", reply_markup=InlineKeyboardMarkup(buttons))


async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancela a sessão atual, uma busca em andamento e o lote de downloads pendente."""
    user_id = update.effective_user.id
    command = update.effective_message
    chat_id = update.effective_chat.id
    key = (chat_id, user_id)

    if not authorized(user_id):
        await safe_delete(command)
        return

    # Cancela uma Busca Global que ainda esteja aguardando as fontes.
    search_task = SEARCH_TASKS.get(user_id)
    if search_task and search_task is not asyncio.current_task():
        search_task.cancel()

    search_msg = SEARCH_MESSAGES.pop(user_id, None)
    if search_msg:
        await safe_delete(search_msg)

    # Invalidar imediatamente qualquer lote de downloads desse usuário.
    ACTIVE_BATCHES.pop(user_id, None)

    session = SESSIONS.pop(key, None)
    if session:
        for message_id in list(session.get("menu_messages", set())):
            try:
                await context.bot.delete_message(chat_id, message_id)
            except Exception:
                pass

    # Apaga também o próprio /cancelar. Não enviamos confirmação para não
    # criar outro rastro no tópico.
    await safe_delete(command)
    log.info("Sessão/lote cancelado | chat=%s | user=%s", chat_id, user_id)


async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not authorized(user_id):
        await temp_error(context.bot, update.effective_chat.id, "⛔ Usuário não autorizado.", update.effective_message.message_thread_id)
        await safe_delete(update.effective_message)
        return

    query_text = " ".join(context.args).strip()
    command = update.effective_message
    if not query_text:
        await temp_error(context.bot, command.chat_id, "Use /bb <nome>", command.message_thread_id)
        await safe_delete(command)
        return

    lock = SEARCH_LOCKS[user_id]
    if lock.locked():
        await safe_delete(command)
        return

    SEARCH_TASKS[user_id] = asyncio.current_task()
    search_msg = None
    try:
        async with lock:
            await safe_delete(command)
            search_msg = await context.bot.send_message(
                command.chat_id,
                "🔎 Buscando...",
                message_thread_id=command.message_thread_id,
            )
            SEARCH_MESSAGES[user_id] = search_msg

            sources = get_all_sources()
            results = await asyncio.gather(
                *(search_one(n, s, query_text) for n, s in sources.items())
            )

            # /cancelar pode ter removido a busca enquanto as fontes respondiam.
            if SEARCH_TASKS.get(user_id) is not asyncio.current_task():
                await safe_delete(search_msg)
                return

            combined = dedupe([x for batch in results for x in batch])
            if not combined:
                await safe_delete(search_msg)
                SEARCH_MESSAGES.pop(user_id, None)
                await temp_error(
                    context.bot,
                    command.chat_id,
                    "❌ Nenhum resultado encontrado.",
                    command.message_thread_id,
                )
                return

            session = {
                "results": combined,
                "query": query_text,
                "thread_id": command.message_thread_id,
                "chat_id": command.chat_id,
                "menu_messages": set(),
                "command_message_id": command.message_id,
                "chapters": [],
                "updated": time.monotonic(),
            }
            SESSIONS[(command.chat_id, user_id)] = session
            session["menu_messages"].add(search_msg.message_id)
            SEARCH_MESSAGES.pop(user_id, None)
            log.info("Busca Global | %r | %d resultados", query_text, len(combined))
            await show_results(search_msg, user_id, 0)
    except asyncio.CancelledError:
        # /cancelar interrompe a tarefa de busca sem deixar menu pendurado.
        if search_msg:
            await safe_delete(search_msg)
        SESSIONS.pop((command.chat_id, user_id), None)
        log.info("Busca cancelada | chat=%s | user=%s", command.chat_id, user_id)
    finally:
        SEARCH_MESSAGES.pop(user_id, None)
        if SEARCH_TASKS.get(user_id) is asyncio.current_task():
            SEARCH_TASKS.pop(user_id, None)


async def select_manga(update, context):
    q = update.callback_query
    await q.answer()
    if not owner_ok(q):
        return
    key = (q.message.chat_id, q.from_user.id)
    session = SESSIONS.get(key)
    if not session:
        await safe_delete(q.message)
        return
    command_id = session.get("command_message_id")
    if command_id:
        try:
            await context.bot.delete_message(q.message.chat_id, command_id)
        except Exception:
            pass
    index = int(q.data.split("|")[1])
    try:
        item = session["results"][index]
        source = get_all_sources()[item["source"]]
        async with asyncio.timeout(45):
            chapters = await source.chapters(item["url"])
        if not chapters:
            await safe_delete(q.message)
            await temp_error(context.bot, q.message.chat_id, "❌ Nenhum capítulo encontrado.", session["thread_id"])
            return
        session.update({"source": source, "source_name": item["source"], "title": item["title"], "chapters": chapters, "updated": time.monotonic()})
        await safe_delete(q.message)
        menu = await context.bot.send_message(
            q.message.chat_id,
            f"📖 {item['title']}\nTotal: {len(chapters)} capítulos",
            message_thread_id=session["thread_id"],
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Baixar tudo", callback_data=f"download_all|0|{q.from_user.id}")],
                [InlineKeyboardButton("📖 Ver capítulos", callback_data=f"chap_page|0|{q.from_user.id}")],
            ]),
        )
        session["menu_messages"].add(menu.message_id)
    except Exception as e:
        log.warning("Capítulos | %s | ERRO | %s", item.get("source", "?"), e)
        await safe_delete(q.message)
        await temp_error(context.bot, q.message.chat_id, "❌ Erro ao obter capítulos.", session["thread_id"])


async def enqueue(update, context, chapters):
    q = update.callback_query
    key = (q.message.chat_id, q.from_user.id)
    session = SESSIONS.get(key)
    if not session:
        return
    batch_id = uuid4().hex
    ACTIVE_BATCHES[q.from_user.id] = batch_id
    for chap in chapters:
        await DOWNLOAD_QUEUE.put({
            "chat_id": q.message.chat_id,
            "thread_id": session["thread_id"],
            "user_id": q.from_user.id,
            "source": session["source"],
            "source_name": session["source_name"],
            "chapter": chap,
            "title": session["title"],
            "batch_id": batch_id,
        })


async def download_all(update, context):
    q = update.callback_query
    await q.answer()
    if not owner_ok(q):
        return
    session = SESSIONS.get((q.message.chat_id, q.from_user.id))
    if not session:
        return
    command_id = session.get("command_message_id")
    if command_id:
        try:
            await context.bot.delete_message(q.message.chat_id, command_id)
        except Exception:
            pass
    await enqueue(update, context, session["chapters"])
    await safe_delete(q.message)
    SESSIONS.pop((q.message.chat_id, q.from_user.id), None)


async def download_one(update, context):
    q = update.callback_query
    await q.answer()
    if not owner_ok(q):
        return
    session = SESSIONS.get((q.message.chat_id, q.from_user.id))
    if not session:
        return
    command_id = session.get("command_message_id")
    if command_id:
        try:
            await context.bot.delete_message(q.message.chat_id, command_id)
        except Exception:
            pass
    index = int(q.data.split("|")[1])
    chapters = session["chapters"]
    if index >= len(chapters):
        return
    await enqueue(update, context, [chapters[index]])
    await safe_delete(q.message)
    SESSIONS.pop((q.message.chat_id, q.from_user.id), None)


async def change_page(update, context):
    q = update.callback_query
    await q.answer()
    if owner_ok(q):
        await show_results(q.message, q.from_user.id, int(q.data.split("|")[1]))


async def change_chap_page(update, context):
    q = update.callback_query
    await q.answer()
    if owner_ok(q):
        await show_chapters(q.message, q.from_user.id, int(q.data.split("|")[1]))


async def back_to_results(update, context):
    q = update.callback_query
    await q.answer()
    if not owner_ok(q):
        return
    session = SESSIONS.get((q.message.chat_id, q.from_user.id))
    if session:
        await show_results(q.message, q.from_user.id, 0)


async def session_cleaner(application):
    while True:
        await asyncio.sleep(60)
        now = time.monotonic()
        for key, session in list(SESSIONS.items()):
            if now - session.get("updated", now) < SESSION_TTL:
                continue
            chat_id, _user_id = key
            command_id = session.get("command_message_id")
            if command_id:
                try:
                    await application.bot.delete_message(chat_id, command_id)
                except Exception:
                    pass
            for message_id in list(session.get("menu_messages", set())):
                try:
                    await application.bot.delete_message(chat_id, message_id)
                except Exception:
                    pass
            SESSIONS.pop(key, None)
            log.info("Sessão expirada e rastros temporários removidos | chat=%s", chat_id)


async def download_worker(application):
    while True:
        job = await DOWNLOAD_QUEUE.get()
        try:
            async with DOWNLOAD_SEMAPHORE:
                source = job["source"]
                chap = job["chapter"]
                if ACTIVE_BATCHES.get(job["user_id"]) != job.get("batch_id"):
                    log.info("Download cancelado/ignorado | %s | %s", job["source_name"], chap.get("name"))
                    continue
                try:
                    async with asyncio.timeout(90):
                        pages = await source.pages(chap["url"])
                except Exception as e:
                    log.warning("Páginas | %s | %s | ERRO | %s", job["source_name"], chap.get("name"), e)
                    await temp_error(application.bot, job["chat_id"], "❌ Erro ao obter páginas.", job["thread_id"])
                    continue
                if not pages:
                    log.warning("Páginas | %s | %s | VAZIO", job["source_name"], chap.get("name"))
                    await temp_error(application.bot, job["chat_id"], "❌ Nenhuma página encontrada.", job["thread_id"])
                    continue
                if ACTIVE_BATCHES.get(job["user_id"]) != job.get("batch_id"):
                    log.info("Download cancelado antes do CBZ | %s | %s", job["source_name"], chap.get("name"))
                    continue
                try:
                    cbz_buffer, cbz_name = await create_cbz(pages, job["title"], f"Cap_{chap.get('chapter_number')}")
                    cbz_buffer.seek(0)
                    await application.bot.send_document(
                        chat_id=job["chat_id"], document=cbz_buffer, filename=cbz_name,
                        message_thread_id=job["thread_id"]
                    )
                    cbz_buffer.close()
                    log.info("Download | %s | %s | OK | %d páginas", job["source_name"], chap.get("name"), len(pages))
                except Exception as e:
                    log.exception("CBZ | %s | %s | ERRO", job["source_name"], chap.get("name"))
                    await temp_error(application.bot, job["chat_id"], "❌ Erro ao criar/enviar CBZ.", job["thread_id"])
        finally:
            DOWNLOAD_QUEUE.task_done()


async def post_init(application):
    application.create_task(download_worker(application))
    application.create_task(session_cleaner(application))


def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).post_init(post_init).build()
    app.add_handler(CommandHandler("bb", buscar))
    app.add_handler(CommandHandler("cancelar", cancelar))
    app.add_handler(CallbackQueryHandler(change_page, pattern=r"^page\|"))
    app.add_handler(CallbackQueryHandler(select_manga, pattern=r"^select\|"))
    app.add_handler(CallbackQueryHandler(download_all, pattern=r"^download_all\|"))
    app.add_handler(CallbackQueryHandler(download_one, pattern=r"^download_one\|"))
    app.add_handler(CallbackQueryHandler(change_chap_page, pattern=r"^chap_page\|"))
    app.add_handler(CallbackQueryHandler(back_to_results, pattern=r"^back\|"))
    log.info("🤖 Bot iniciado")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
