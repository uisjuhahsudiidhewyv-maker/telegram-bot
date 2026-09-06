import os
import asyncio
import logging
import math
import re
import unicodedata
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from utils.loader import get_all_sources
from utils.cbz import create_cbz
from auth import authorized

logging.basicConfig(level=logging.INFO)
DOWNLOAD_QUEUE = asyncio.Queue()
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(2)
SEARCH_CACHE = {}
RESULTS_PER_PAGE = 10
CHAPTERS_PER_PAGE = 15
TRACE_DELETE_DELAY = float(os.getenv("TRACE_DELETE_DELAY", "5"))


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def title_matches(title, query):
    t = norm(title); q = norm(query)
    return bool(q) and all(word in t for word in q.split())


def is_owner(query):
    try:
        return query.from_user.id == int(query.data.split("|")[-1])
    except Exception:
        return False


async def safe_delete(bot, chat_id, message_id):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def delete_later(bot, chat_id, message_id, delay=TRACE_DELETE_DELAY):
    if delay > 0:
        await asyncio.sleep(delay)
    await safe_delete(bot, chat_id, message_id)


async def worker():
    while True:
        job = await DOWNLOAD_QUEUE.get()
        try:
            await send_chapter(job)
        except Exception as e:
            print(f"Erro worker: {type(e).__name__}: {e}")
        finally:
            DOWNLOAD_QUEUE.task_done()


async def send_chapter(job):
    async with DOWNLOAD_SEMAPHORE:
        bot = job["bot"]
        chat_id = job["chat_id"]
        thread_id = job.get("thread_id")
        source = job["source"]
        chapter = job["chapter"]
        title = job.get("title") or chapter.get("manga_title") or "Manga"
        try:
            pages = await source.pages(chapter["url"])
        except Exception as e:
            print(f"[{getattr(source,'name',type(source).__name__)}] páginas: {type(e).__name__}: {e}")
            m = await bot.send_message(chat_id, "❌ Erro ao obter páginas.", message_thread_id=thread_id)
            asyncio.create_task(delete_later(bot, chat_id, m.message_id))
            return
        if not pages:
            m = await bot.send_message(chat_id, "❌ Nenhuma página encontrada.", message_thread_id=thread_id)
            asyncio.create_task(delete_later(bot, chat_id, m.message_id))
            return
        try:
            cbz_buffer, cbz_name = await create_cbz(pages, title, f"Cap_{chapter.get('chapter_number')}")
        except Exception as e:
            print(f"[{getattr(source,'name',type(source).__name__)}] CBZ: {type(e).__name__}: {e}")
            m = await bot.send_message(chat_id, "❌ Erro ao criar CBZ.", message_thread_id=thread_id)
            asyncio.create_task(delete_later(bot, chat_id, m.message_id))
            return
        try:
            await bot.send_document(chat_id, document=cbz_buffer, filename=cbz_name, message_thread_id=thread_id)
        finally:
            cbz_buffer.close()


async def buscar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not authorized(update.effective_user.id):
        return
    query_text = " ".join(context.args).strip()
    if not query_text:
        m = await update.message.reply_text("Use /bb <nome>")
        asyncio.create_task(delete_later(context.bot, m.chat_id, m.message_id))
        return
    # Delete the user's command immediately: it is a bot-related trace.
    asyncio.create_task(safe_delete(context.bot, update.effective_chat.id, update.message.message_id))
    msg = await update.message.reply_text("🔎 Buscando em todas as fontes...")
    results = []
    sources = get_all_sources()
    async def one(name, source):
        try:
            res = await source.search(query_text)
            out=[]
            for m in res or []:
                title=m.get("title") if isinstance(m,dict) else None
                url=m.get("url") if isinstance(m,dict) else None
                if title and url and title_matches(title, query_text):
                    out.append({"source":name,"title":title,"url":url})
            return out
        except Exception as e:
            print(f"[{name}] busca: {type(e).__name__}: {e}")
            return []
    batches = await asyncio.gather(*(one(n,s) for n,s in sources.items()))
    seen=set()
    for batch in batches:
        for item in batch:
            key=(item["source"],item["url"])
            if key not in seen:
                seen.add(key); results.append(item)
    if not results:
        await safe_delete(context.bot, msg.chat_id, msg.message_id)
        m=await context.bot.send_message(msg.chat_id,"❌ Nenhum resultado encontrado.", message_thread_id=msg.message_thread_id)
        asyncio.create_task(delete_later(context.bot,m.chat_id,m.message_id))
        return
    SEARCH_CACHE[msg.message_id] = {"results":results,"query":query_text}
    await show_results(msg, update.effective_user.id, 0)


async def show_results(message, user_id, page):
    entry=SEARCH_CACHE.get(message.message_id)
    if not entry: return
    data=entry["results"]; total_pages=max(1,math.ceil(len(data)/RESULTS_PER_PAGE))
    start=page*RESULTS_PER_PAGE; end=start+RESULTS_PER_PAGE
    buttons=[[InlineKeyboardButton(f"{x['title']} ({x['source']})",callback_data=f"select|{i}|{user_id}")] for i,x in enumerate(data[start:end],start=start)]
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("«",callback_data=f"page|{page-1}|{user_id}"))
    if page<total_pages-1: nav.append(InlineKeyboardButton("»",callback_data=f"page|{page+1}|{user_id}"))
    if nav: buttons.append(nav)
    await message.edit_text(f"📚 Resultados ({page+1}/{total_pages})",reply_markup=InlineKeyboardMarkup(buttons))


async def show_chapters(message, context, page, user_id):
    chapters=context.user_data.get("chapters",[])
    if not chapters:
        await message.edit_text("❌ Nenhum capítulo encontrado."); return
    total_pages=max(1,math.ceil(len(chapters)/CHAPTERS_PER_PAGE)); start=page*CHAPTERS_PER_PAGE; end=start+CHAPTERS_PER_PAGE
    buttons=[]
    for i,chap in enumerate(chapters[start:end],start=start):
        label=chap.get("chapter_number") or chap.get("name") or "?"
        buttons.append([InlineKeyboardButton(f"Cap {label}",callback_data=f"download_one|{i}|{user_id}")])
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("«",callback_data=f"chap_page|{page-1}|{user_id}"))
    if page<total_pages-1: nav.append(InlineKeyboardButton("»",callback_data=f"chap_page|{page+1}|{user_id}"))
    if nav: buttons.append(nav)
    buttons.append([InlineKeyboardButton("🔙 Voltar",callback_data=f"back|0|{user_id}")])
    await message.edit_text(f"📖 Capítulos ({page+1}/{total_pages})",reply_markup=InlineKeyboardMarkup(buttons))


async def change_page(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    await show_results(q.message,q.from_user.id,int(q.data.split("|")[1]))


async def select_manga(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    try:
        index=int(q.data.split("|")[1]); entry=SEARCH_CACHE[q.message.message_id]; data=entry["results"][index]
        source=get_all_sources()[data["source"]]
        chapters=await source.chapters(data["url"])
    except Exception as e:
        print(f"[select] {type(e).__name__}: {e}"); await q.message.edit_text("❌ Erro ao obter capítulos."); asyncio.create_task(delete_later(context.bot,q.message.chat_id,q.message.message_id)); return
    # Search results are no longer needed.
    SEARCH_CACHE.pop(q.message.message_id,None)
    context.user_data.clear()
    context.user_data.update({"chapters":chapters,"source":source,"title":data["title"]})
    buttons=[[InlineKeyboardButton("📥 Baixar tudo",callback_data=f"download_all|0|{q.from_user.id}")],[InlineKeyboardButton("📖 Ver capítulos",callback_data=f"chap_page|0|{q.from_user.id}")]]
    await q.message.edit_text(f"📖 {data['title']}\nTotal: {len(chapters)} capítulos",reply_markup=InlineKeyboardMarkup(buttons))


async def queue_chapters(q, context, chapters):
    thread_id = getattr(q.message, "message_thread_id", None)
    for chap in chapters:
        await DOWNLOAD_QUEUE.put({"bot":context.bot,"chat_id":q.message.chat_id,"thread_id":thread_id,"source":context.user_data["source"],"chapter":chap,"title":context.user_data.get("title")})
    # Remove all bot UI/context; only downloaded CBZ messages remain.
    await safe_delete(context.bot,q.message.chat_id,q.message.message_id)
    context.user_data.clear()


async def download_all(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    chapters=list(context.user_data.get("chapters",[]))
    if not chapters: return
    await queue_chapters(q,context,chapters)


async def download_one(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    try: index=int(q.data.split("|")[1]); chap=context.user_data["chapters"][index]
    except Exception: return
    await DOWNLOAD_QUEUE.put({"bot":context.bot,"chat_id":q.message.chat_id,"thread_id":getattr(q.message,"message_thread_id",None),"source":context.user_data["source"],"chapter":chap,"title":context.user_data.get("title")})
    await safe_delete(context.bot,q.message.chat_id,q.message.message_id)
    context.user_data.clear()


async def change_chap_page(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    await show_chapters(q.message,context,int(q.data.split("|")[1]),q.from_user.id)


async def back_to_results(update, context):
    q=update.callback_query; await q.answer()
    if not is_owner(q): return
    await show_results(q.message,q.from_user.id,0)


def main():
    app=ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("bb",buscar))
    app.add_handler(CallbackQueryHandler(change_page,pattern="^page"))
    app.add_handler(CallbackQueryHandler(select_manga,pattern="^select"))
    app.add_handler(CallbackQueryHandler(download_all,pattern="^download_all"))
    app.add_handler(CallbackQueryHandler(download_one,pattern="^download_one"))
    app.add_handler(CallbackQueryHandler(change_chap_page,pattern="^chap_page"))
    app.add_handler(CallbackQueryHandler(back_to_results,pattern="^back"))
    async def startup(application): asyncio.create_task(worker())
    app.post_init=startup
    print("🤖 Bot iniciado")
    app.run_polling(drop_pending_updates=True)

if __name__=="__main__": main()
