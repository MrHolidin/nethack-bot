"""python -m nhbot [SEED]: play one game and print its summary."""
import json
import sys
import time

from nhbot import Bot

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
t = time.time()
s = Bot(seed=seed).run()
s["secs"] = round(time.time() - t, 1)
print(json.dumps(s, ensure_ascii=False, indent=1))
