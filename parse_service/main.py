"""Parse microservice: builds CST and AST trees for source files.

Port: 8002
Endpoints:
    GET  /                service info
    GET  /health          liveness probe
    POST /parse/cst       file -> Concrete Syntax Tree (all tokens)
    POST /parse/ast       file -> Abstract Syntax Tree (semantic nodes)
    POST /parse/both      file -> {cst, ast, stats}
    POST /render          file -> ASCII tree rendering of cst/ast
    POST /obsidian        file -> Obsidian vault (interlinked notes + Mermaid)
    POST /obsidian/zip    file -> downloadable .zip Obsidian vault

Supported: COBOL (dedicated parser), Python (ast + tokenize),
everything else falls back to a generic line/token parser.
"""

from __future__ import annotations

import io
import sys
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from . import obsidian
from .parsers import cobol_parser, generic_parser, python_parser

# Deeply nested / very large files (50k-60k lines) can exceed Python's default
# recursion limit while walking the tree; raise it and keep hot helpers iterative.
sys.setrecursionlimit(200000)

app = FastAPI(
    title="CST/AST Parse Service",
    description="Parses source files of any language into Concrete Syntax Trees and "
                "Abstract Syntax Trees. Handles very large files (50k-60k+ lines).",
    version="1.1.0",
)

# ~200 MB cap comfortably covers 50k-60k+ line files in any language.
MAX_BYTES = 200 * 1024 * 1024

EXT_LANG = {
    ".cbl": "cobol", ".cob": "cobol", ".cpy": "cobol",
    ".py": "python",
}


@app.get("/")
def info():
    return {"service": "cst-ast-parser", "port": 8002, "docs": "/docs",
            "engines": ["cobol", "python", "generic"],
            "exports": ["obsidian-vault", "obsidian-zip"]}


@app.get("/health")
def health():
    return {"status": "ok"}


async def _read_upload(file: UploadFile, language: str | None):
    raw = await file.read()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 200 MB)")
    source = raw.decode("utf-8", errors="replace")
    if not language or language == "auto":
        ext = "." + (file.filename or "").rsplit(".", 1)[-1].lower()
        language = EXT_LANG.get(ext, "generic")
    return source, language


def _dispatch(source, language):
    """Return (cst, ast, error). Falls back to the generic parser on failure."""
    error = None
    ast_tree = None
    if language == "cobol":
        cst, ast_tree = cobol_parser.build_trees(source)
    elif language == "python":
        cst, ast_tree, error = python_parser.build_trees(source)
        if ast_tree is None:
            # syntax error -> generic CST still valid, AST unavailable
            pass
    else:
        cst, ast_tree = generic_parser.build_trees(source, language)
    return cst, ast_tree, error


def _count_nodes(node):
    """Iterative node count (safe for very large trees)."""
    if not isinstance(node, dict):
        return 0
    total = 0
    stack = [node]
    while stack:
        cur = stack.pop()
        total += 1
        for child in cur.get("children", []):
            if isinstance(child, dict):
                stack.append(child)
    return total


def _max_depth(node):
    """Iterative max-depth (explicit stack, no recursion)."""
    if not isinstance(node, dict):
        return 0
    deepest = 0
    stack = [(node, 1)]
    while stack:
        cur, depth = stack.pop()
        deepest = max(deepest, depth)
        for child in cur.get("children", []):
            if isinstance(child, dict):
                stack.append((child, depth + 1))
    return deepest


@app.post("/parse/cst")
async def parse_cst(file: UploadFile = File(...), language: str = Form("auto")):
    source, language = await _read_upload(file, language)
    cst, _, _ = _dispatch(source, language)
    return {"filename": file.filename, "language": language, "cst": cst}


@app.post("/parse/ast")
async def parse_ast(file: UploadFile = File(...), language: str = Form("auto")):
    source, language = await _read_upload(file, language)
    _, ast_tree, error = _dispatch(source, language)
    if ast_tree is None:
        raise HTTPException(422, {"detail": "Could not build AST", "error": error})
    return {"filename": file.filename, "language": language, "ast": ast_tree}


@app.post("/parse/both")
async def parse_both(file: UploadFile = File(...), language: str = Form("auto")):
    source, language = await _read_upload(file, language)
    cst, ast_tree, error = _dispatch(source, language)
    stats = {
        "lines": source.count("\n") + 1,
        "size_bytes": len(source.encode("utf-8", errors="replace")),
        "cst_nodes": _count_nodes(cst),
        "ast_nodes": _count_nodes(ast_tree) if ast_tree else 0,
        "cst_max_depth": _max_depth(cst),
        "ast_max_depth": _max_depth(ast_tree) if ast_tree else 0,
        "tokens": cst.get("token_count"),
    }
    return {"filename": file.filename, "language": language,
            "cst": cst, "ast": ast_tree, "stats": stats, "parse_error": error}


def _render(node, prefix="", is_last=True, lines=None):
    lines = [] if lines is None else lines
    label = node.get("type", "?")
    extras = []
    for key in ("name", "verb", "text", "token_type"):
        if node.get(key):
            v = node[key]
            extras.append(f"{key}={v if isinstance(v, str) else ''}"[:60])
    if node.get("tokens") and not node.get("children"):
        extras.append("tokens=" + " ".join(t["text"] for t in node["tokens"])[:60])
    line = f"{prefix}{'└── ' if is_last else '├── '}{label}"
    if extras:
        line += f"  [{', '.join(extras)}]"
    lines.append(line)
    kids = [c for c in node.get("children", []) if isinstance(c, dict)]
    ext_kids = []
    for key in ("statements", "sections", "paragraphs", "file_control", "branches",
                "then", "else", "body", "items"):
        val = node.get(key)
        if isinstance(val, list):
            ext_kids.extend([k for k in val if isinstance(k, dict) and k is not node])
    all_kids = kids + ([] if kids and not ext_kids else ext_kids)
    if node.get("type") in ("identification_division", "environment_division",
                            "data_division", "procedure_division", "program",
                            "source_file", "section", "paragraph") and ext_kids and not kids:
        all_kids = ext_kids
    extension = "│   " if not is_last else "    "
    for idx, kid in enumerate(all_kids):
        _render(kid, prefix + extension, idx == len(all_kids) - 1, lines)
    return lines


@app.post("/render")
async def render(file: UploadFile = File(...), language: str = Form("auto"),
                 tree: str = Form("ast")):
    """Return an ASCII rendering of the requested tree (ast|cst)."""
    source, language = await _read_upload(file, language)
    cst, ast_tree, _ = _dispatch(source, language)
    root = ast_tree if tree == "ast" else cst
    if root is None:
        raise HTTPException(422, "Tree unavailable")
    text = "\n".join(_render(root))
    return {"filename": file.filename, "language": language, "tree": tree,
            "rendering": text}


@app.post("/obsidian")
async def obsidian_export(file: UploadFile = File(...), language: str = Form("auto"),
                          tree: str = Form("ast"), max_nodes: int = Form(1500)):
    """Return an Obsidian vault (map of path -> markdown) for the tree.

    Includes a native Mermaid graph in `00-index.md` plus one interlinked
    note per node under `nodes/` for Obsidian's Graph view.
    """
    source, language = await _read_upload(file, language)
    file_label = file.filename or "source"
    cst, ast_tree, error = _dispatch(source, language)
    root = ast_tree if tree == "ast" else cst
    if root is None:
        raise HTTPException(422, {"detail": "Tree unavailable", "error": error})
    vault = obsidian.build_vault(root, file_label, tree_kind=tree,
                                 max_nodes=max_nodes)
    return {"filename": file.filename, "language": language, "tree": tree,
            "node_count": vault["node_count"], "truncated": vault["truncated"],
            "mermaid": vault["mermaid"], "files": vault["files"]}


@app.post("/obsidian/zip")
async def obsidian_zip(file: UploadFile = File(...), language: str = Form("auto"),
                       tree: str = Form("ast"), max_nodes: int = Form(5000)):
    """Return a downloadable .zip Obsidian vault (unzip and open in Obsidian)."""
    source, language = await _read_upload(file, language)
    file_label = file.filename or "source"
    cst, ast_tree, error = _dispatch(source, language)
    root = ast_tree if tree == "ast" else cst
    if root is None:
        raise HTTPException(422, {"detail": "Tree unavailable", "error": error})
    vault = obsidian.build_vault(root, file_label, tree_kind=tree,
                                 max_nodes=max_nodes)
    base = (file.filename or "vault").rsplit(".", 1)[0]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in vault["files"].items():
            zf.writestr(f"{base}/{path}", content)
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{base}-obsidian.zip"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)
