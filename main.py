import os, asyncio, logging, math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from utils.loader import get_all_sources
from utils.cbz import create_cbz
from auth import authorized

logging.basicConfig(level=logging.INFO)
DOWNLOAD_QUEUE=asyncio.Queue(); DOWNLOAD_SEMAPHORE=asyncio.Semaphore(2)
SEARCH_CACHE={}; RESULTS_PER_PAGE=10; CHAPTERS_PER_PAGE=15

def is_owner(q):
    try:return q.from_user.id==int(q.data.split('|')[-1])
    except:return False
async def delete_message(bot,chat_id,message_id):
    try: await bot.delete_message(chat_id=chat_id,message_id=message_id)
    except Exception: pass
async def temp_message(bot,chat_id,thread_id,text,delay=2):
    try:
        m=await bot.send_message(chat_id=chat_id,message_thread_id=thread_id,text=text)
        await asyncio.sleep(delay); await delete_message(bot,chat_id,m.message_id)
    except Exception: pass
async def reject(update):
    try:
        if update.message: await update.message.delete()
        elif update.callback_query: await update.callback_query.answer('⛔ Não autorizado',show_alert=True)
    except Exception: pass
def target(message): return {'chat_id':message.chat_id,'thread_id':getattr(message,'message_thread_id',None)}

async def worker():
    while True:
        job=await DOWNLOAD_QUEUE.get()
        try: await send_chapter(job)
        except Exception as e: logging.exception('Erro worker: %s',e)
        finally: DOWNLOAD_QUEUE.task_done()
async def send_chapter(job):
    async with DOWNLOAD_SEMAPHORE:
        bot=job['bot']; t=job['target']; source=job['source']; chapter=job['chapter']
        try: pages=await source.pages(chapter['url'])
        except Exception as e:
            logging.exception('Páginas %s: %s',source.name,e); await temp_message(bot,t['chat_id'],t['thread_id'],'❌ Não foi possível obter as páginas.'); return
        if not pages:
            logging.error('Nenhuma página: %s %s',source.name,chapter.get('url')); await temp_message(bot,t['chat_id'],t['thread_id'],'❌ Nenhuma página encontrada.'); return
        try:
            cbz_buffer,cbz_name=await create_cbz(pages,chapter.get('manga_title') or job.get('title') or 'Manga',f"Cap_{chapter.get('chapter_number')}")
        except Exception as e:
            logging.exception('CBZ %s: %s',source.name,e); await temp_message(bot,t['chat_id'],t['thread_id'],'❌ Erro ao criar CBZ.'); return
        try:
            await bot.send_document(chat_id=t['chat_id'],message_thread_id=t['thread_id'],document=cbz_buffer,filename=cbz_name)
        finally: cbz_buffer.close()

async def search_source(name,source,query):
    try:
        res=await source.search(query); q=' '.join(query.lower().split()); out=[]
        for m in res:
            title=str(m.get('title') or ''); norm=' '.join(title.lower().split())
            if title and all(part in norm for part in q.split()): out.append({'source':name,'title':title,'url':m.get('url')})
        return out
    except Exception as e: logging.warning('Fonte %s falhou na busca: %s',name,e); return []
async def buscar(update:Update,context:ContextTypes.DEFAULT_TYPE):
    if not authorized(update.effective_user.id): await reject(update); return
    # apagar o comando do usuário imediatamente
    await delete_message(context.bot,update.effective_chat.id,update.message.message_id)
    query_text=' '.join(context.args).strip()
    if not query_text:
        await temp_message(context.bot,update.effective_chat.id,getattr(update.message,'message_thread_id',None),'Use /bb <nome>'); return
    msg=await context.bot.send_message(chat_id=update.effective_chat.id,message_thread_id=getattr(update.message,'message_thread_id',None),text='🔎 Buscando em todas as fontes...')
    results=await asyncio.gather(*(search_source(n,s,query_text) for n,s in get_all_sources().items()))
    combined=[]; seen=set()
    for r in results:
        for item in r:
            key=(item['source'],item['url']);
            if key not in seen: seen.add(key); combined.append(item)
    if not combined:
        await delete_message(context.bot,msg.chat_id,msg.message_id); return
    SEARCH_CACHE[msg.message_id]=combined
    await show_results(msg,update.effective_user.id,0)
async def show_results(message,user_id,page):
    data=SEARCH_CACHE.get(message.message_id,[]); total=max(1,math.ceil(len(data)/RESULTS_PER_PAGE)); start=page*RESULTS_PER_PAGE; end=start+RESULTS_PER_PAGE
    buttons=[[InlineKeyboardButton(f"{x['title']} ({x['source']})",callback_data=f"select|{i}|{user_id}")] for i,x in enumerate(data[start:end],start=start)]
    nav=[]
    if page>0: nav.append(InlineKeyboardButton('«',callback_data=f'page|{page-1}|{user_id}'))
    if page<total-1: nav.append(InlineKeyboardButton('»',callback_data=f'page|{page+1}|{user_id}'))
    if nav: buttons.append(nav)
    await message.edit_text(f'📚 Resultados ({page+1}/{total})',reply_markup=InlineKeyboardMarkup(buttons))
async def show_chapters(message,context,page,user_id):
    chapters=context.user_data.get('chapters',[]); total=max(1,math.ceil(len(chapters)/CHAPTERS_PER_PAGE)); start=page*CHAPTERS_PER_PAGE; end=start+CHAPTERS_PER_PAGE
    buttons=[[InlineKeyboardButton(f"Cap {c.get('chapter_number')}",callback_data=f'download_one|{i}|{user_id}')] for i,c in enumerate(chapters[start:end],start=start)]
    nav=[]
    if page>0:nav.append(InlineKeyboardButton('«',callback_data=f'chap_page|{page-1}|{user_id}'))
    if page<total-1:nav.append(InlineKeyboardButton('»',callback_data=f'chap_page|{page+1}|{user_id}'))
    if nav:buttons.append(nav)
    buttons.append([InlineKeyboardButton('🔙 Voltar',callback_data=f'back|0|{user_id}')])
    await message.edit_text(f'📖 Capítulos ({page+1}/{total})',reply_markup=InlineKeyboardMarkup(buttons))
async def change_page(update,context):
    q=update.callback_query; await q.answer()
    if not is_owner(q):return
    await show_results(q.message,q.from_user.id,int(q.data.split('|')[1]))
async def select_manga(update,context):
    q=update.callback_query; await q.answer()
    if not is_owner(q):return
    idx=int(q.data.split('|')[1]); data=SEARCH_CACHE.get(q.message.message_id,[])[idx]; src=get_all_sources()[data['source']]; tgt=target(q.message)
    await delete_message(context.bot,q.message.chat_id,q.message.message_id); SEARCH_CACHE.pop(q.message.message_id,None)
    try: chapters=await src.chapters(data['url'])
    except Exception as e: logging.exception('Capítulos %s: %s',src.name,e); await temp_message(context.bot,tgt['chat_id'],tgt['thread_id'],'❌ Não foi possível obter os capítulos.'); return
    if not chapters: await temp_message(context.bot,tgt['chat_id'],tgt['thread_id'],'❌ Nenhum capítulo encontrado.'); return
    context.user_data.update(chapters=chapters,source=src,title=data['title'],target=tgt)
    m=await context.bot.send_message(chat_id=tgt['chat_id'],message_thread_id=tgt['thread_id'],text=f"📖 {data['title']}\nTotal: {len(chapters)} capítulos",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('📥 Baixar tudo',callback_data=f'download_all|0|{q.from_user.id}')],[InlineKeyboardButton('📖 Ver capítulos',callback_data=f'chap_page|0|{q.from_user.id}')]]))
    context.user_data['menu_id']=m.message_id
async def remove_menu(context,chat_id,message_id):
    if message_id: await delete_message(context.bot,chat_id,message_id)
async def download_all(update,context):
    q=update.callback_query; await q.answer()
    if not is_owner(q):return
    chapters=context.user_data.get('chapters',[]); src=context.user_data.get('source'); tgt=context.user_data.get('target') or target(q.message); title=context.user_data.get('title','Manga')
    await remove_menu(context,q.message.chat_id,q.message.message_id)
    for ch in chapters: await DOWNLOAD_QUEUE.put({'bot':context.bot,'target':tgt,'source':src,'chapter':ch,'title':title})
    context.user_data.clear()
async def download_one(update,context):
    q=update.callback_query; await q.answer()
    if not is_owner(q):return
    idx=int(q.data.split('|')[1]); chapters=context.user_data.get('chapters',[]); src=context.user_data.get('source'); tgt=context.user_data.get('target') or target(q.message); title=context.user_data.get('title','Manga')
    if idx>=len(chapters):return
    await remove_menu(context,q.message.chat_id,q.message.message_id)
    await DOWNLOAD_QUEUE.put({'bot':context.bot,'target':tgt,'source':src,'chapter':chapters[idx],'title':title}); context.user_data.clear()
async def change_chap_page(update,context):
    q=update.callback_query; await q.answer()
    if is_owner(q): await show_chapters(q.message,context,int(q.data.split('|')[1]),q.from_user.id)
async def back_to_results(update,context):
    q=update.callback_query; await q.answer()
    if not is_owner(q):return
    await show_results(q.message,q.from_user.id,0)
def main():
    app=ApplicationBuilder().token(os.getenv('BOT_TOKEN')).build()
    app.add_handler(CommandHandler('bb',buscar)); app.add_handler(CallbackQueryHandler(change_page,pattern='^page')); app.add_handler(CallbackQueryHandler(select_manga,pattern='^select')); app.add_handler(CallbackQueryHandler(download_all,pattern='^download_all')); app.add_handler(CallbackQueryHandler(download_one,pattern='^download_one')); app.add_handler(CallbackQueryHandler(change_chap_page,pattern='^chap_page')); app.add_handler(CallbackQueryHandler(back_to_results,pattern='^back'))
    async def startup(app): asyncio.create_task(worker())
    app.post_init=startup; print('🤖 Bot iniciado'); app.run_polling(drop_pending_updates=True)
if __name__=='__main__': main()
