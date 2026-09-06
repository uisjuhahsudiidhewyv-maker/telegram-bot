import asyncio
from collections import defaultdict

from utils.cbz import stream_zip_and_send

TASK_QUEUE = asyncio.Queue()
CANCEL_FLAGS = defaultdict(bool)


def cancel_task(user_id: int):
    CANCEL_FLAGS[user_id] = True


async def worker(application):
    while True:
        task = await TASK_QUEUE.get()

        user_id = task["user_id"]
        chat_id = task["chat_id"]
        chapters = task["chapters"]
        source = task["source"]
        title = task["title"]

        CANCEL_FLAGS[user_id] = False

        try:
            await application.bot.send_message(
                chat_id,
                "📦 Iniciando download..."
            )

            await stream_zip_and_send(
                application=application,
                chat_id=chat_id,
                user_id=user_id,
                chapters=chapters,
                source=source,
                title=title,
                cancel_flags=CANCEL_FLAGS
            )

        except Exception as e:
            print("Erro no worker:", e)
            await application.bot.send_message(
                chat_id,
                "❌ Erro durante o processo."
            )

        TASK_QUEUE.task_done()
