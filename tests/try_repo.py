"""Generic end-to-end test: run a whole repository through the gateway pipeline.

Sweeps every (non-binary, reasonably sized) source file in a repo directory
through the gateway ``/analyze`` endpoint (detect language -> build CST + AST)
and prints a per-extension summary report. With ``--vault`` it also builds a
combined, namespaced Obsidian vault from one representative file per language.

Usage:
    python tests/try_repo.py <repo_dir> [--vault] [--max N] [--quiet]

Example:
    python tests/try_repo.py _acas --vault

Run from the project root with the gateway + services already up.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = "http://127.0.0.1:8000"

# Extensions that are (almost always) binary / non-source -> never analyzed.
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".zip", ".gz", ".tar",
    ".dll", ".so", ".a", ".o", ".obj", ".exe", ".class", ".jar", ".whl",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".prn",
    ".mp3", ".mp4", ".gitkeep", ".drawio",
}
TEXT_SKIP = {".md", ".template"}  # docs / templates: parseable but noisy
MAX_BYTES = 2 * 1024 * 1024       # skip anything huge for a bulk sweep


def iter_files(repo: Path):
    for path in sorted(repo.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        ext = path.suffix.lower()
        if ext in BINARY_EXT or ext in TEXT_SKIP:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        yield path


def analyze(client: httpx.Client, path: Path):
    resp = client.post(
        GATEWAY + "/analyze",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        params={"include_cst": "true", "include_ast": "true"},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def obsidian_for(client: httpx.Client, path: Path, max_nodes=400):
    resp = client.post(
        GATEWAY + "/obsidian",
        files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        data={"tree": "ast", "max_nodes": max_nodes},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_sweep(client: httpx.Client, files, quiet=False):
    by_ext = defaultdict(lambda: {"n": 0, "ok": 0, "ast": 0, "cst": 0, "langs": set()})
    total = ok = 0
    errors = []
    biggest = None

    for path in files:
        ext = path.suffix.lower() or "(none)"
        total += 1
        if not quiet and total % 50 == 0:
            print(f"  ... {total} files")
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
        b = by_ext[ext]
        b["n"] += 1
        b["ok"] += 1 if ast_n else 0
        b["ast"] += ast_n
        b["cst"] += cst_n
        b["langs"].add(det.get("language", "?"))
        size = stats.get("size_bytes", 0)
        if biggest is None or size > biggest[0]:
            biggest = (size, path.name, stats)

    print(f"\n{'='*72}\nSweep: {total} source files -> gateway /analyze\n{'='*72}")
    hdr = f"{'ext':9} {'files':>5} {'ASTok':>6} {'AST nodes':>10} {'CST nodes':>10}  detected"
    print(hdr)
    print("-" * len(hdr))
    for ext, b in sorted(by_ext.items(), key=lambda kv: -kv[1]["n"]):
        langs = ",".join(sorted(x for x in b["langs"] if x))
        print(f"{ext:9} {b['n']:>5} {b['ok']:>6} {b['ast']:>10} {b['cst']:>10}  {langs}")
    print("-" * len(hdr))
    print(f"non-empty AST: {ok}/{total}   errors: {len(errors)}")
    if errors:
        print("  first errors:", errors[:5])
    if biggest:
        size, name, stats = biggest
        print(f"largest: {name}  ({size/1024:.1f} KB, {stats.get('lines','?')} lines, "
              f"CST {stats.get('cst_nodes')} nodes)")
    return total, ok, errors, by_ext


def build_vault(client: httpx.Client, files, repo_name, max_progs=10):
    vault_dir = ROOT / "obsidian_vault" / repo_name
    # one representative (reasonably sized) file per extension
    picks = {}
    for path in files:
        ext = path.suffix.lower() or "(none)"
        if ext not in picks and 200 < path.stat().st_size < 200_000:
            picks[ext] = path
    chosen = list(picks.values())[:max_progs]

    if vault_dir.exists():
        for f in vault_dir.rglob("*.md"):
            f.unlink()
    vault_dir.mkdir(parents=True, exist_ok=True)

    link_re = re.compile(r"\[\[([0-9A-Za-z-]+)\]\]")
    print(f"\n=== Obsidian vault ({len(chosen)} programs) -> "
          f"{vault_dir.relative_to(ROOT)} ===")
    total_nodes = 0
    for path in chosen:
        data = obsidian_for(client, path)
        prefix = re.sub(r"[^A-Za-z0-9]+", "-", path.stem).strip("-").lower()
        for rel, content in data["files"].items():
            folder, _, fname = rel.rpartition("/")
            base, _, extn = fname.rpartition(".")
            fixed = link_re.sub(lambda m: f"[[{prefix}-{m.group(1)}]]", content)
            out = vault_dir / (f"{folder}/{prefix}-{base}.{extn}" if folder
                               else f"{prefix}-{base}.{extn}")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(fixed, encoding="utf-8")
        total_nodes += data["node_count"]
        print(f"  {path.name:26} -> {data['language']:10} {data['node_count']:>4} nodes")
    print(f"vault notes: {len(list(vault_dir.rglob('*.md')))}  nodes: {total_nodes}")
    print(f"Open in Obsidian as a vault, then Graph view: {vault_dir}")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    flags = {a for a in argv[1:] if a.startswith("-")}
    if not args:
        print(__doc__)
        sys.exit(1)
    repo = (ROOT / args[0]).resolve()
    if not repo.exists():
        print(f"repo not found at {repo} — clone it first.")
        sys.exit(1)
    files = list(iter_files(repo))
    maxn = 0
    for a in argv[1:]:
        if a.startswith("--max"):
            maxn = int(a.split("=")[1]) if "=" in a else 0
    if maxn:
        files = files[:maxn]
    with httpx.Client() as client:
        run_sweep(client, files, quiet="--quiet" in flags)
        if "--vault" in flags:
            build_vault(client, files, repo.name)
    print("\nDone.")


if __name__ == "__main__":
    main(sys.argv)
