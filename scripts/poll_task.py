import json
import time
import urllib.request

tid = "45c7572d01b5489f86458bcb030b1c32"
for _ in range(90):
    with urllib.request.urlopen(f"http://127.0.0.1:8000/api/tasks/{tid}") as r:
        s = json.load(r)
    print(f"[{s['status']}] {s['percent']}% {s['message']}")
    if s["status"] in ("success", "failed"):
        print(json.dumps(s.get("result"), ensure_ascii=False, indent=2))
        print("error:", s.get("error"))
        break
    time.sleep(2)
else:
    print("timeout waiting for task")
