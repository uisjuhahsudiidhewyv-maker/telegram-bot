import asyncio

TASK_QUEUE = asyncio.Queue()
CANCEL_FLAGS = {}
USER_CONTEXT = {}

def cancel_task(user_id):
    CANCEL_FLAGS[user_id] = True

def clear_cancel(user_id):
    CANCEL_FLAGS.pop(user_id, None)

def is_cancelled(user_id):
    return CANCEL_FLAGS.get(user_id, False)
