"""Obsidian export: turn a CST/AST tree into an Obsidian-ready knowledge graph.

Obsidian renders:
  * a **Graph view** from interlinked Markdown notes (one note per node,
    connected with [[wikilinks]]), and
  * **Mermaid** diagrams inside notes (native rendering).

So a syntax tree becomes a navigable, visual graph of nodes:

  * `00-index.md`             - overview, metadata, a Mermaid diagram, links
  * `nodes/<id>-<label>.md`   - one note per tree node with Parent/Children links

Pure standard library; returns an in-memory vault (dict of path -> content)
which the caller writes to disk or downloads.
"""

from __future__ import annotations

import re
from collections import deque

# Keys that (may) hold child nodes, checked in order.
CHILD_KEYS = (
    "children", "statements", "sections", "paragraphs", "branches",
    "then", "else", "body", "items", "arguments", "fields", "members",
    "elements", "declarations",
)
# Keys that hold non-node data and must never be treated as children.
NON_NODE_KEYS = {
    "type", "token_type", "tokens", "loc", "ctx", "name", "verb", "text",
    "value", "level", "picture", "usage", "occurs", "redefines",
    "condition", "subject", "operands", "assign", "clauses", "token_count",
    "comments", "using", "kind", "line", "col", "start", "end", "raw", "indent",
}


def _is_node(obj):
    return isinstance(obj, dict) and isinstance(obj.get("type"), str)


def extract_children(node):
    """Return child node dicts, using known keys first then a safe fallback."""
    kids = []
    for key in CHILD_KEYS:
        val = node.get(key)
        if isinstance(val, list):
            kids.extend(v for v in val if _is_node(v))
        elif _is_node(val):
            kids.append(val)
    if kids:
        return kids
    # Fallback (e.g. Python ast trees): any nested dict/list carrying a "type".
    for key, val in node.items():
        if key in NON_NODE_KEYS:
            continue
        if _is_node(val):
            kids.append(val)
        elif isinstance(val, list):
            kids.extend(v for v in val if _is_node(v))
    return kids


def node_label(node):
    t = str(node.get("type", "node"))
    for key in ("name", "verb", "text"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return f"{t} {val.strip()[:40]}"
    line = node.get("line")
    if isinstance(line, int):
        return f"{t} L{line}"
    return t


def _slug(label):
    clean = re.sub(r"[^A-Za-z0-9]+", "-", label).strip("-").lower()
    return clean[:48] or "node"


def _mermaid_label(label):
    # Mermaid-safe: strip quotes/brackets/backticks/pipes/newlines.
    return re.sub(r"[\"'`\[\]{}<>|]", "", label).replace("\n", " ").strip()


def _index_nodes(tree, max_nodes):
    """BFS the tree; return (order, parents, children, truncated)."""
    order, parents, children = [], {}, {}
    queue = deque([(None, tree)])
    next_id = 0
    truncated = False
    while queue:
        pid, node = queue.popleft()
        if next_id >= max_nodes:
            truncated = True
            break
        nid = next_id
        next_id += 1
        order.append((nid, node))
        parents[nid] = pid
        children.setdefault(nid, [])
        if pid is not None:
            children[pid].append(nid)
        for ch in extract_children(node):
            queue.append((nid, ch))
    return order, parents, children, truncated


def build_vault(tree, file_label, tree_kind="ast", max_nodes=1500,
                mermaid_limit=150):
    """Build an Obsidian vault. Returns {files, mermaid, node_count, truncated}."""
    order, parents, children, truncated = _index_nodes(tree, max_nodes)
    node_by_id = dict(order)
    titles = {nid: f"{nid:04d}-{_slug(node_label(node))}" for nid, node in order}

    files = {}
    for nid, node in order:
        label = node_label(node)
        title = titles[nid]
        pid = parents.get(nid)
        kids = children.get(nid, [])
        lines = [
            "---",
            f"tags: [ast, {tree_kind}, {node.get('type', 'node')}]",
            f"node_id: {nid}",
            "---",
            "",
            f"# {label}",
            "",
            f"- **type:** `{node.get('type', 'node')}`",
        ]
        for meta in ("name", "verb", "level", "picture", "usage", "value",
                     "line", "col", "language"):
            val = node.get(meta)
            if isinstance(val, (str, int)) and str(val).strip():
                lines.append(f"- **{meta}:** `{val}`")
        for extra in ("operands", "condition", "subject"):
            val = node.get(extra)
            if isinstance(val, list) and val:
                lines.append(f"- **{extra}:** `{' '.join(map(str, val))[:120]}`")
        lines.append("")
        if pid is not None:
            lines.append(f"**Parent:** [[{titles[pid]}]]")
        else:
            lines.append("**Parent:** (root) — see [[00-index]]")
        if kids:
            lines += ["", "**Children:**"]
            lines += [f"- [[{titles[k]}]] {node_label(node_by_id[k])}" for k in kids]
        files[f"nodes/{title}.md"] = "\n".join(lines) + "\n"

    # ---- Mermaid graph (bounded for readability)
    shown = order[:mermaid_limit]
    shown_ids = {nid for nid, _ in shown}
    mm = ["graph TD"]
    for nid, node in shown:
        mm.append(f'  n{nid}["{_mermaid_label(node_label(node))}"]')
    for nid, _ in shown:
        pid = parents.get(nid)
        if pid in shown_ids:
            mm.append(f"  n{pid} --> n{nid}")
    if len(order) > mermaid_limit or truncated:
        mm.append(f'  note["… {len(order)} nodes total, diagram truncated to {mermaid_limit}"]')
    mermaid = "\n".join(mm)

    # ---- Index note
    first_children = children.get(0, [])[:30]
    idx_lines = [
        "---",
        f"tags: [ast, index, {tree_kind}]",
        "---",
        "",
        f"# {file_label}",
        "",
        f"**Tree kind:** `{tree_kind}`  ",
        f"**Nodes:** {len(order)}" + (" (truncated)" if truncated else ""),
        "",
        "## Graph (Mermaid — native Obsidian rendering)",
        "",
        "```mermaid",
        mermaid,
        "```",
        "",
        "## Nodes",
        f"- Root: [[{titles[0]}]] {node_label(tree)}",
    ]
    for cid in first_children:
        idx_lines.append(f"  - [[{titles[cid]}]] {node_label(node_by_id[cid])}")
    idx_lines += ["", "> Open the **Graph view** in Obsidian to explore the tree."]
    files["00-index.md"] = "\n".join(idx_lines) + "\n"

    return {"files": files, "mermaid": mermaid, "node_count": len(order),
            "truncated": truncated}
