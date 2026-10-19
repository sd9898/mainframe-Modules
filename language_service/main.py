"""Language Detection microservice.

Port: 8001
Endpoints:
    GET  /                 service info
    GET  /health           liveness probe
    POST /detect-language  multipart file upload -> detected language
"""

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from .detector import detect

app = FastAPI(
    title="Language Detection Service",
    description="Detects the programming language of a source file "
                "(COBOL, Python, JS, C/C++, Java, Go, ... any text language).",
    version="1.1.0",
)

# ~200 MB cap comfortably covers very large files (50k-60k+ lines).
MAX_BYTES = 200 * 1024 * 1024


class TextPayload(BaseModel):
    filename: str | None = None
    content: str


@app.get("/")
def info():
    return {"service": "language-detection", "port": 8001, "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/detect-language")
async def detect_language_endpoint(
    file: UploadFile | None = File(None),
    payload: TextPayload | None = None,
):
    """Detect language from an uploaded file, or from raw text JSON body."""
    if file is not None:
        raw = await file.read()
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, "File too large (max 200 MB)")
        content = raw.decode("utf-8", errors="replace")
        filename = file.filename
    elif payload is not None:
        content = payload.content
        filename = payload.filename
    else:
        raise HTTPException(400, "Provide either a 'file' upload or a JSON text payload")

    return {"filename": filename, **detect(filename, content)}
