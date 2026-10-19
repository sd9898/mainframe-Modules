"""API Gateway: single entry point that orchestrates the microservices.

Port: 8000
Endpoints:
    GET  /                    service map & usage
    GET  /health              aggregate health of all services
    POST /analyze             file -> language detection + CST + AST (one call)
    POST /detect-language     -> language-service
    POST /parse/cst           -> parse-service
    POST /parse/ast           -> parse-service
    POST /parse/both          -> parse-service
    POST /render              -> parse-service (tree=ast|cst)

Each upstream URL can be overridden with env vars:
    LANGUAGE_SERVICE_URL (default http://127.0.0.1:8001)
    PARSE_SERVICE_URL    (default http://127.0.0.1:8002)
"""

import os

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

LANGUAGE_SERVICE_URL = os.getenv("LANGUAGE_SERVICE_URL", "http://127.0.0.1:8001")
PARSE_SERVICE_URL = os.getenv("PARSE_SERVICE_URL", "http://127.0.0.1:8002")
TIMEOUT = httpx.Timeout(300.0)  # generous for very large (50k-60k+ line) files

app = FastAPI(
    title="CST/AST Gateway",
    description="Gateway over the Language Detection and CST/AST Parse microservices.",
    version="1.0.0",
)


async def _forward(url: str, request: Request, files=None, data=None):
    params = dict(request.query_params)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, files=files, data=data, params=params)
    except httpx.ConnectError:
        raise HTTPException(503, f"Upstream service unavailable: {url}")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


@app.get("/")
def info():
    return {
        "service": "gateway",
        "port": 8000,
        "upstreams": {
            "language_service": LANGUAGE_SERVICE_URL,
            "parse_service": PARSE_SERVICE_URL,
        },
        "endpoints": {
            "POST /analyze": "upload a file -> detection + CST + AST in one response",
            "POST /detect-language": "upload a file -> detected language",
            "POST /parse/cst": "upload a file -> Concrete Syntax Tree",
            "POST /parse/ast": "upload a file -> Abstract Syntax Tree",
            "POST /parse/both": "upload a file -> CST + AST + stats",
            "POST /render": "upload a file -> ASCII tree (form field tree=ast|cst)",
            "GET /health": "aggregate health",
        },
    }


@app.get("/health")
async def health():
    async with httpx.AsyncClient(timeout=5.0) as client:
        results = {"gateway": "ok"}
        for name, base in (("language_service", LANGUAGE_SERVICE_URL),
                           ("parse_service", PARSE_SERVICE_URL)):
            try:
                r = await client.get(base + "/health")
                results[name] = r.json() if r.status_code == 200 else "degraded"
            except httpx.HTTPError:
                results[name] = "unreachable"
    return results


@app.post("/analyze")
async def analyze(file: UploadFile = File(...),
                  include_cst: bool = True, include_ast: bool = True):
    """Full pipeline: detect language, then build CST and/or AST."""
    raw = await file.read()

    # 1. language detection (language microservice)
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            det = await client.post(
                LANGUAGE_SERVICE_URL + "/detect-language",
                files={"file": (file.filename, raw, "application/octet-stream")},
            )
            detection = det.json()
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Language service unreachable: {e}")

    # 2. parse (parse microservice) with the detected language
    data = {"language": detection.get("language", "generic")}
    if include_cst and include_ast:
        path = "/parse/both"
    elif include_cst:
        path = "/parse/cst"
    elif include_ast:
        path = "/parse/ast"
    else:
        raise HTTPException(400, "Nothing selected: set include_cst and/or include_ast")
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            pr = await client.post(
                PARSE_SERVICE_URL + path,
                files={"file": (file.filename, raw, "application/octet-stream")},
                data=data,
            )
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Parse service unreachable: {e}")
    if pr.status_code >= 400:
        raise HTTPException(pr.status_code, pr.text)
    parsed = pr.json()

    result = {
        "filename": file.filename,
        "size_bytes": len(raw),
        "detection": detection,
    }
    if include_cst:
        result["cst"] = parsed.get("cst")
    if include_ast:
        result["ast"] = parsed.get("ast")
    if "stats" in parsed:
        result["stats"] = parsed["stats"]
    if parsed.get("parse_error"):
        result["parse_error"] = parsed["parse_error"]
    return result


@app.post("/detect-language")
async def detect_language(request: Request, file: UploadFile = File(None)):
    raw = await file.read() if file else b""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                LANGUAGE_SERVICE_URL + "/detect-language",
                files={"file": (file.filename if file else "unnamed", raw,
                                "application/octet-stream")},
            )
    except httpx.HTTPError as e:
        raise HTTPException(503, f"Language service unreachable: {e}")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.text)
    return resp.json()


@app.post("/parse/cst")
async def proxy_parse_cst(request: Request, file: UploadFile = File(...),
                          language: str = Form("auto")):
    return await _forward(PARSE_SERVICE_URL + "/parse/cst", request,
                          files={"file": (file.filename, await file.read(),
                                         "application/octet-stream")},
                          data={"language": language})


@app.post("/parse/ast")
async def proxy_parse_ast(request: Request, file: UploadFile = File(...),
                          language: str = Form("auto")):
    return await _forward(PARSE_SERVICE_URL + "/parse/ast", request,
                          files={"file": (file.filename, await file.read(),
                                         "application/octet-stream")},
                          data={"language": language})


@app.post("/parse/both")
async def proxy_parse_both(request: Request, file: UploadFile = File(...),
                           language: str = Form("auto")):
    return await _forward(PARSE_SERVICE_URL + "/parse/both", request,
                          files={"file": (file.filename, await file.read(),
                                         "application/octet-stream")},
                          data={"language": language})


@app.post("/render")
async def proxy_render(request: Request, file: UploadFile = File(...),
                       language: str = Form("auto"), tree: str = Form("ast")):
    return await _forward(PARSE_SERVICE_URL + "/render", request,
                          files={"file": (file.filename, await file.read(),
                                         "application/octet-stream")},
                          data={"language": language, "tree": tree})
