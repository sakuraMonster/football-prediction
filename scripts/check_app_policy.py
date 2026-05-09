import asyncio
import threading
from src.app import _base
print('after import src.app policy =', type(asyncio.get_event_loop_policy()).__name__)

def worker():
    p = asyncio.get_event_loop_policy()
    loop = p.new_event_loop()
    print('worker policy =', type(p).__name__)
    print('worker new loop =', type(loop).__name__)
    loop.close()

threading.Thread(target=worker).start()
