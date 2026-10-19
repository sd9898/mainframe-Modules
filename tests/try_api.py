"""End-to-end API test against the running microservices.

Start the services first (start_all.bat or docker compose up), then:
    python tests/try_api.py
"""

import json
import os
import sys

import httpx

BASE = os.getenv("GATEWAY_URL", "http://127.0.0.1:8000")
LANG = os.getenv("LANGUAGE_SERVICE_URL", "http://127.0.0.1:8001")
PARSE = os.getenv("PARSE_SERVICE_URL", "http://127.0.0.1:8002")
ROOT = os.path.join(os.path.dirname(__file__), "..")

failed = 0


def check(name, cond, detail=""):
    global failed
    status = "PASS" if cond else "FAIL"
    if not cond:
        failed += 1
    print(f"[{status}] {name}" + (f"  -> {detail}" if detail and not cond else ""))


def upload(path):
    with open(path, "rb") as fh:
        return {"file": (os.path.basename(path), fh.read(), "application/octet-stream")}


# ---- health
r = httpx.get(BASE + "/health", timeout=30)
check("gateway /health", r.status_code == 200, r.text)
h = r.json()
check("language service reachable", h.get("language_service") == {"status": "ok"}, str(h))
check("parse service reachable", h.get("parse_service") == {"status": "ok"}, str(h))

# ---- language service directly
r = httpx.post(LANG + "/detect-language", files=upload(os.path.join(ROOT, "samples", "HelloWorld.cbl")), timeout=30)
check("detect COBOL", r.status_code == 200 and r.json()["language"] == "cobol", r.text[:200])

r = httpx.post(LANG + "/detect-language", files=upload(os.path.join(ROOT, "samples", "demo.py")), timeout=30)
check("detect Python", r.json()["language"] == "python", r.text[:200])

# ---- parse service directly
r = httpx.post(PARSE + "/parse/both", files=upload(os.path.join(ROOT, "samples", "HelloWorld.cbl")),
               data={"language": "cobol"}, timeout=60)
check("parse/both cobol", r.status_code == 200 and r.json()["cst"] and r.json()["ast"], r.text[:300])
body = r.json()
check("cobol program name", body["ast"]["name"] == "HELLO", json.dumps(body["ast"])[:200])
check("cobol stats", body["stats"]["tokens"] > 100, str(body["stats"]))

r = httpx.post(PARSE + "/render", files=upload(os.path.join(ROOT, "samples", "HelloWorld.cbl")),
               data={"language": "cobol", "tree": "ast"}, timeout=60)
check("render ast tree", r.status_code == 200 and "MAIN-PARA" in r.json()["rendering"], r.text[:200])

r = httpx.post(PARSE + "/parse/both", files=upload(os.path.join(ROOT, "samples", "demo.py")), timeout=60)
check("parse/both python (auto lang)", r.status_code == 200
      and r.json()["ast"]["type"] == "Module", r.text[:200])

r = httpx.post(PARSE + "/parse/cst", files=upload(os.path.join(ROOT, "samples", "app.js")), timeout=60)
check("parse generic js cst", r.status_code == 200 and r.json()["cst"]["children"], r.text[:200])

# ---- gateway full pipeline
r = httpx.post(BASE + "/analyze", files=upload(os.path.join(ROOT, "samples", "HelloWorld.cbl")), timeout=60)
check("gateway /analyze cobol", r.status_code == 200, r.text[:300])
if r.status_code == 200:
    a = r.json()
    check("analyze detection", a["detection"]["language"] == "cobol", str(a["detection"]))
    check("analyze has cst+ast", a.get("cst") and a.get("ast"))

r = httpx.post(BASE + "/analyze", files=upload(os.path.join(ROOT, "samples", "demo.py")), timeout=60)
check("gateway /analyze python", r.status_code == 200 and r.json()["detection"]["language"] == "python",
      r.text[:200])

r = httpx.post(BASE + "/analyze", files=upload(os.path.join(ROOT, "samples", "app.js")),
               params={"include_cst": "false"}, timeout=60)
check("gateway /analyze js ast-only", r.status_code == 200, r.text[:200])

print()
print("ALL E2E TESTS PASSED" if failed == 0 else f"{failed} E2E TEST(S) FAILED")
sys.exit(1 if failed else 0)
