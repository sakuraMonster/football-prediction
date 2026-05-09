import os, sys
sys.path.append(os.getcwd())
import asyncio
import threading
import nest_asyncio
from playwright.sync_api import sync_playwright

print('policy before', type(asyncio.get_event_loop_policy()).__name__)

nest_asyncio.apply()
print('policy after', type(asyncio.get_event_loop_policy()).__name__)

def worker():
    p = asyncio.get_event_loop_policy()
    loop = asyncio.new_event_loop()
    print('worker loop before playwright =', type(loop).__name__)
    asyncio.set_event_loop(loop)
    try:
        pw = sync_playwright().start()
        print('playwright ok')
        pw.stop()
    except Exception as e:
        import traceback
        print('playwright err', repr(e))
        traceback.print_exc()
    finally:
        try:
            loop.close()
        except Exception:
            pass

thread = threading.Thread(target=worker)
thread.start()
thread.join()
