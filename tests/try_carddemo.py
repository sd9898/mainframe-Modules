"""End-to-end test against the real AWS mainframe modernization card-demo repo.

Runs every source file in ``_carddemo/`` through the gateway ``/analyze``
pipeline (detect language -> build CST + AST) and prints a summary report.
Also builds a combined multi-language Obsidian vault under
``obsidian_vault/carddemo/`` (namespaced so all programs show in one graph).

Usage:  python tests/try_carddemo.py [--vault]
Run from the project root with the gateway + services already up.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT / "_carddemo"
GATEWAY = "http://127.0.0.1:8000"
VAULT_DIR = ROOT / "obsidian_vault" / "carddemo"

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".gitkeep", ".md",
            ".drawio", ".xlsx", ".pdf", ".gz", ".ico"}
MAX_BYTES = 2 * 1024 * 1024  # skip anything huge for this bulk sweep


def _files():
    for path in sorted(REPO.rglob("*")):
        if not path.is_file():
            continue
        if ".git" in path.parts:
            continue
        if path.suffix.lower() in SKIP_EXT:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        yield path


def analyze(client: httpx.Client, path: Path):
    raw = path.read_bytes()
    resp = client.post(
        GATEWAY + "/analyze",
        files={"file": (path.name, raw, "application/octet-stream")},
        params={"include_cst": "true", "include_ast": "true"},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def obsidian_for(client: httpx.Client, path: Path, max_nodes=400):
    raw = path.read_bytes()
    resp = client.post(
        GATEWAY + "/obsidian",
        files={"file": (path.name, raw, "application/octet-stream")},
        data={"tree": "ast", "max_nodes": max_nodes},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_sweep(client: httpx.Client):
    by_ext = defaultdict(lambda: {"n": 0, "ok": 0, "ast": 0, "cst": 0, "langs": set()})
    total = ok = empty_ast = 0
    errors = []
    biggest = None  # (size_bytes, name, stats)

    for path in _files():
        ext = path.suffix.lower() or "(none)"
        total += 1
        try:
            data = analyze(client, path)
        except Exception as e:  # noqa: BLE001
            errors.append((path.name, str(e)[:80]))
            continue
        stats = data.get("stats", {})
        det = data.get("detection", {})
        ast_n = stats.get("ast_nodes", 0)
        cst_n = stats.get("cst_nodes", 0)
        if ast_n:
            ok += 1
        else:
            empty_ast += 1
        b = by_ext[ext]
        b["n"] += 1
        b["ok"] += 1 if ast_n else 0
        b["ast"] += ast_n
        b["cst"] += cst_n
        b["langs"].add(det.get("language", "?"))
        size = stats.get("size_bytes", len(path.read_bytes()))
        if biggest is None or size > biggest[0]:
            biggest = (size, path.name, stats)

    print(f"\n=== Card-demo sweep: {total} source files through /analyze ===")
    hdr = f"{'ext':7} {'files':>5} {'AST-ok':>6} {'AST nodes':>10} {'CST nodes':>10}  detected"
    print(hdr)
    print("-" * len(hdr))
    for ext, b in sorted(by_ext.items(), key=lambda kv: -kv[1]["n"]):
        langs = ",".join(sorted(x for x in b["langs"] if x))
        print(f"{ext:7} {b['n']:>5} {b['ok']:>6} {b['ast']:>10} {b['cst']:>10}  {langs}")
    print("-" * len(hdr))
    print(f"parsed with non-empty AST: {ok}/{total}   (empty AST: {empty_ast})")
    if errors:
        print(f"errors: {len(errors)} -> {errors[:5]}")
    else:
        print("errors: 0")
    if biggest:
        size, name, stats = biggest
        print(f"largest file: {name}  ({size/1024:.1f} KB, "
              f"{stats.get('lines','?')} lines, CST {stats.get('cst_nodes')} nodes, "
              f"{stats.get('cst_max_depth')} deep)")
    return total, ok, errors


def build_vault(client: httpx.Client):
    """Build one combined, namespaced Obsidian vault from a multi-language set."""
    # one representative file per interesting extension
    picks = {}
    for path in _files():
        ext = path.suffix.lower()
        if ext in picks:
            continue
        # prefer a reasonably sized example
        if 200 < path.stat().st_size < 200_000:
            picks[ext] = path
    wanted = [".cbl", ".cpy", ".jcl", ".bms", ".ddl", ".asm", ".sh", ".mac"]
    chosen = [picks[w] for w in wanted if w in picks]
    if not chosen:
        chosen = list(picks.values())[:8]

    if VAULT_DIR.exists():
        for f in VAULT_DIR.rglob("*.md"):
            f.unlink()
    VAULT_DIR.mkdir(parents=True, exist_ok=True)

    link_re = re.compile(r"\[\[([0-9A-Za-z-]+)\]\]")
    print(f"\n=== Building combined Obsidian vault ({len(chosen)} programs) -> "
          f"{VAULT_DIR.relative_to(ROOT)} ===")
    total_nodes = 0
    for path in chosen:
        data = obsidian_for(client, path)
        prefix = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
        for rel, content in data["files"].items():
            # namespace basename so links are unique across all programs
            folder, _, fname = rel.rpartition("/")
            base, _, extn = fname.rpartition(".")
            new_base = f"{prefix}-{base}"
            fixed = link_re.sub(lambda m: f"[[{prefix}-{m.group(1)}]]", content)
            out = VAULT_DIR / (f"{folder}/{new_base}.{extn}" if folder
                               else f"{new_base}.{extn}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(fixed, encoding="utf-8")
        total_nodes += data["node_count"]
        print(f"  {path.name:24} -> {data['language']:8} "
              f"{data['node_count']:>4} nodes")
    print(f"vault notes: {len(list(VAULT_DIR.rglob('*.md')))}   total nodes: {total_nodes}")
    print("Open this folder as a vault in Obsidian, then switch to Graph view.")


def main():
    if not REPO.exists():
        print(f"repo not found at {REPO} — clone it first.")
        sys.exit(1)
    with httpx.Client() as client:
        total, ok, errors = run_sweep(client)
        if "--vault" in sys.argv:
            build_vault(client)
    print("\nDone.")


if __name__ == "__main__":
    main()
