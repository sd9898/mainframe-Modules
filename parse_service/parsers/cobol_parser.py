"""COBOL parser: builds a CST (all tokens, lossless) and an AST (semantic tree).

Supports fixed- and free-format COBOL common constructs:
  - the four divisions
  - IDENTIFICATION paragraphs (PROGRAM-ID, AUTHOR, REMARKS, ...)
  - ENVIRONMENT DIVISION file control (SELECT ... ASSIGN)
  - DATA DIVISION sections (WORKING-STORAGE / FILE / LINKAGE),
    FD/SD entries and level-number data items (group nesting by level)
  - PROCEDURE DIVISION paragraphs/sections and statements including
    blocks: IF/ELSE/END-IF, EVALUATE/WHEN/END-EVALUATE, PERFORM/END-PERFORM

The CST keeps every token (keywords, punctuation, periods) grouped in the
concrete structure; the AST is derived from it: verb + operands, typed
statement nodes, structured data descriptions, punctuation dropped.
"""

import re

RESERVED = {
    "IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE", "DIVISION",
    "SECTION", "PROGRAM-ID", "AUTHOR", "INSTALLATION", "DATE-WRITTEN",
    "DATE-COMPILED", "REMARKS", "FILE-CONTROL", "INPUT-OUTPUT", "RESERVED",
    "SELECT", "ASSIGN", "ORGANIZATION", "IS", "SEQUENTIAL", "INDEXED",
    "RELATIVE", "ACCESS", "RECORD", "FD", "SD", "WORKING-STORAGE",
    "LINKAGE", "FILE", "PICTURE", "PIC", "USAGE", "VALUE", "RUND",
    "OCCURS", "TIMES", "FILLER", "REDEFINES", "SYNCHRONIZED", "SYNC",
    "TO", "FROM", "BY", "GIVING", "REPLACING", "WITH", "OF", "IN", "NOT",
    "ZERO", "ZEROS", "SPACE", "SPACES", "HIGH-VALUES", "LOW-VALUES", "NULL",
    "ALL", "THAN", "GREATER", "LESS", "EQUAL", "AND", "OR", "TRUE", "FALSE",
    "OTHERS", "THEN", "ELSE", "END-IF", "WHEN", "EVALUATE", "END-EVALUATE",
    "PERFORM", "END-PERFORM", "UNTIL", "THRU", "THROUGH", "VARYING",
    "AFTER", "TEST", "BEFORE", "ENDING", "MOVE", "DISPLAY", "ADD",
    "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE", "CALL", "OPEN", "CLOSE",
    "READ", "WRITE", "REWRITE", "DELETE", "START", "SET", "INITIALIZE",
    "INSPECT", "STRING", "UNSTRING", "GO", "STOP", "EXIT", "IF",
    "CONTINUE", "NEXT", "SENTENCE", "RETURN", "RELEASE", "ACCEPT",
    "SORT", "MERGE", "INPUT", "OUTPUT", "I-O", "CONTROL", "AREA",
    "CODE", "RECORDING", "LABEL", "RECORDS", "SIZE", "TOPIC", "USING",
    "REFERENCE", "MEMORY", "RETURNING", "INTO", "UPON", "FROM", "GIVING",
}

# verbs that open a statement (or a body block)
STATEMENT_VERBS = {
    "MOVE", "DISPLAY", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "COMPUTE",
    "CALL", "OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE", "START",
    "SET", "INITIALIZE", "INSPECT", "STRING", "UNSTRING", "GO", "STOP",
    "EXIT", "IF", "EVALUATE", "PERFORM", "CONTINUE", "RETURN", "RELEASE",
    "ACCEPT", "SORT", "MERGE", "NEXT",
}

# structural tokens that terminate the current statement / open or close blocks
STRUCTURAL = {"ELSE", "END-IF", "WHEN", "END-EVALUATE", "END-PERFORM", "THEN"}


def tok(type_, text, line, col):
    return {"type": type_, "text": text, "line": line, "col": col}


def classify(word, line, col):
    u = word.upper()
    if word == ".":
        return tok("period", word, line, col)
    if word in {",", ";", ":"}:
        return tok("punctuation", word, line, col)
    if word.startswith('"') or word.startswith("'"):
        return tok("literal", word, line, col)
    if u in RESERVED:
        return tok("keyword", word, line, col)
    if re.match(r"^\d+(\.\d+)?$", word):
        return tok("number", word, line, col)
    if word in {"=", "+", "-", "*", "/", "<", ">", "<=", ">=", "<>", "==", "**", "%"}:
        return tok("operator", word, line, col)
    if word in {"(", ")"}:
        return tok("punctuation", word, line, col)
    return tok("identifier", word, line, col)


def looks_fixed_format(lines):
    for line in lines[:50]:
        if len(line) >= 7 and line[:6].strip().isdigit():
            return True
        if len(line) >= 7 and line[6] in ("*", "/") and not line[:6].strip():
            return True
    return False


def tokenize(source):
    """Split source into typed tokens with line/col info. Periods stay tokens."""
    lines = source.splitlines()
    fixed = looks_fixed_format(lines)
    tokens = []
    for ln, raw in enumerate(lines, 1):
        content, col_offset = raw, 1
        if fixed:
            indicator = raw[6] if len(raw) > 6 else " "
            if indicator in ("*", "/"):
                tokens.append(tok("comment", indicator + " " + raw[7:].strip(), ln, 1))
                continue
            content = raw[7:]
            col_offset = 8
        stripped = content.strip()
        if not stripped:
            continue
        if stripped.startswith("*>") or stripped.startswith("/"):
            tokens.append(tok("comment", stripped, ln, col_offset))
            continue
        col = col_offset + (len(content) - len(content.lstrip()))
        for m in re.finditer(r'"[^"]*"|\'[^\']*\'|[^\s]+', stripped):
            word = m.group(0)
            wcol = col + m.start()
            if len(word) > 1 and word[-1] in ".,;:" and not re.match(r"^\d+\.\d+$", word):
                core, tail = word[:-1], word[-1]
                tail_type = "period" if tail == "." else "punctuation"
                if core and core != ".":
                    tokens.append(classify(core, ln, wcol))
                tokens.append(tok(tail_type, tail, ln, wcol + len(word) - 1))
            else:
                tokens.append(classify(word, ln, wcol))
    return tokens


def words_of(tokens):
    """Token texts without periods or comments (AST view)."""
    return [t["text"] for t in tokens if t["type"] not in ("period", "comment")]


def group_paragraphs(tokens):
    """Split a token list into period-terminated sequences (paragraphs)."""
    groups, cur = [], []
    for t in tokens:
        cur.append(t)
        if t["type"] == "period":
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


# ---------------------------------------------------------------- divisions
def split_divisions(tokens):
    """Return [(division_name, header_tokens, body_tokens), ...]."""
    real = [t for t in tokens if t["type"] != "comment"]
    n = len(real)
    result, pre, i = [], [], 0

    def division_at(j):
        if j + 1 >= n:
            return None
        u0, u1 = real[j]["text"].upper(), real[j + 1]["text"].upper()
        if u1 == "DIVISION" and u0 in ("IDENTIFICATION", "ID", "ENVIRONMENT", "DATA", "PROCEDURE"):
            return "IDENTIFICATION" if u0 == "ID" else u0
        return None

    while i < n:
        div = division_at(i)
        if not div:
            pre.append(real[i])
            i += 1
            continue
        j = i + 2
        if j < n and real[j]["type"] == "period":
            j += 1
        # PROCEDURE DIVISION USING / GIVING header continuation
        while j < n and real[j]["text"].upper() in ("USING", "GIVING"):
            while j < n and real[j]["type"] != "period":
                j += 1
            j += 1  # consume the period
        header = real[i:j]
        body = []
        i = j
        while i < n and not division_at(i):
            body.append(real[i])
            i += 1
        result.append((div, header, body))
    if pre:
        result.insert(0, ("REMARKS", [], pre))
    return result


# ------------------------------------------------------- IDENTIFICATION
IDENT_PARAS = ("PROGRAM-ID", "AUTHOR", "INSTALLATION", "DATE-WRITTEN",
               "DATE-COMPILED", "REMARKS")


def _merge_orphan_headers(paragraphs):
    """Fix 'PROGRAM-ID. HELLO.' style: the name period ends the paragraph-name
    itself, so its operands land in the next group; merge them back."""
    out = []
    pending = None
    for p in paragraphs:
        w = words_of(p)
        if pending is not None:
            out.append(pending + p)
            pending = None
            continue
        if len(w) == 1 and w[0].upper() in IDENT_PARAS:
            pending = list(p)
            continue
        out.append(p)
    if pending is not None:
        out.append(pending)
    return out


def build_identification(body):
    paragraphs = _merge_orphan_headers(group_paragraphs(body))
    cst_children = [{"type": "paragraph", "tokens": p, "children": []} for p in paragraphs]
    ast_children = []
    for p in paragraphs:
        w = words_of(p)
        if not w:
            continue
        head = w[0].upper()
        if head == "PROGRAM-ID":
            ast_children.append({"type": "program_identification",
                                 "name": " ".join(w[1:])})
        elif head in IDENT_PARAS[1:]:
            ast_children.append({"type": head.lower().replace("-", "_"),
                                 "remark": " ".join(w[1:])})
    return cst_children, {"type": "identification_division", "children": ast_children}


# ------------------------------------------------------- ENVIRONMENT
def build_environment(body):
    paragraphs = group_paragraphs(body)
    cst_children = [{"type": "paragraph", "tokens": p, "children": []} for p in paragraphs]
    ast = {"type": "environment_division", "children": []}
    for p in paragraphs:
        w = words_of(p)
        up = [x.upper() for x in w]
        if "SECTION" in up:
            ast["children"].append({"type": "section",
                                    "name": " ".join(w[:up.index("SECTION")])})
            continue
        if "SELECT" in up:
            rest = w[up.index("SELECT") + 1:]
            name = rest[0] if rest else ""
            assign = ""
            if "ASSIGN" in [x.upper() for x in rest]:
                ai = [x.upper() for x in rest].index("ASSIGN")
                assign = " ".join(x for x in rest[ai + 1:] if x.upper() != "TO")
            entry = {"type": "file_selection", "file_name": name,
                     "assign": assign, "clauses": " ".join(rest[1:])}
            ast["children"].append(entry)
    return cst_children, ast


# ------------------------------------------------------- DATA
def build_data(body):
    # split into sections: WORKING-STORAGE / FILE / LINKAGE
    sections, cur_name, cur_tokens, cur_header = [], None, [], []
    i, n = 0, len(body)
    while i < n:
        u = body[i]["text"].upper()
        nxt = body[i + 1]["text"].upper() if i + 1 < n else ""
        if nxt == "SECTION" and u in ("WORKING-STORAGE", "LINKAGE", "FILE", "SCREEN"):
            if cur_name or cur_tokens:
                sections.append((cur_name, cur_header, cur_tokens))
            cur_header = body[i:i + 2]
            cur_name, cur_tokens = u, []
            i += 2
            if i < n and body[i]["type"] == "period":
                cur_header.append(body[i])
                i += 1
            continue
        cur_tokens.append(body[i])
        i += 1
    if cur_name or cur_tokens:
        sections.append((cur_name, cur_header, cur_tokens))

    cst_children, sec_asts = [], []
    for name, header_toks, toks in sections:
        paragraphs = group_paragraphs(toks)
        cst_children.append({
            "type": "section",
            "tokens": header_toks,
            "children": [{"type": "paragraph", "tokens": p, "children": []}
                         for p in paragraphs]})
        sec_asts.append(_data_section_ast(name, paragraphs))
    return cst_children, {"type": "data_division", "children": sec_asts}


def _data_section_ast(name, paragraphs):
    sec = {"type": ((name or "Unnamed").lower().replace("-", "_") + "_section"),
           "name": name or "UNNAMED", "children": []}
    stack = [(0, sec)]  # (level, ast node) for group nesting
    for p in paragraphs:
        w = words_of(p)
        if not w:
            continue
        up = [x.upper() for x in w]
        if re.match(r"^\d{1,2}$", w[0]):  # data item with level number
            level = int(w[0])
            item = _data_item(level, w[1:])
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack[-1][1]["children"].append(item)
            if level == 1 or level in (77, 66, 0):
                stack.append((level, item))
            else:
                stack.append((level, item))  # groups nest further levels
        elif up and up[0] in ("FD", "SD"):
            rec = {"type": "file_description" if up[0] == "FD" else "sort_description",
                   "kind": up[0], "name": w[1] if len(w) > 1 else "",
                   "record": " ".join(w[2:]), "children": []}
            sec["children"].append(rec)
            stack = [(0, rec)]
        elif "SECTION" in up:
            pass
        else:
            sec["children"].append({"type": "entry", "text": " ".join(w)})
    return sec


def _data_item(level, words):
    item = {"type": "data_item", "level": level, "name": "", "picture": None,
            "usage": None, "value": None, "occurs": None, "redefines": None,
            "children": []}
    clause_kw = {"PIC", "PICTURE", "USAGE", "VALUE", "OCCURS", "REDEFINES",
                 "SYNCHRONIZED", "SYNC", "EXTERNAL", "GLOBAL", "BLANK"}
    up = [w.upper() for w in words]
    name_parts, i = [], 0
    while i < len(words) and up[i] not in clause_kw:
        name_parts.append(words[i])
        i += 1
    item["name"] = " ".join(name_parts)
    while i < len(words):
        u = up[i]
        if u in ("PIC", "PICTURE"):
            i += 1
            if i < len(words) and up[i] == "IS":
                i += 1
            pic = []
            while i < len(words) and up[i] not in clause_kw:
                pic.append(words[i])
                i += 1
            item["picture"] = " ".join(pic)
        elif u == "USAGE":
            i += 1
            if i < len(words) and up[i] == "IS":
                i += 1
            usage = []
            while i < len(words) and up[i] not in clause_kw:
                usage.append(words[i])
                i += 1
            item["usage"] = " ".join(usage)
        elif u == "VALUE":
            i += 1
            if i < len(words) and up[i] in ("IS", "RUND"):
                i += 1
            val = []
            while i < len(words) and up[i] not in clause_kw:
                val.append(words[i])
                i += 1
            item["value"] = " ".join(val)
        elif u == "OCCURS":
            i += 1
            occ = []
            while i < len(words) and up[i] not in clause_kw:
                occ.append(words[i])
                i += 1
            item["occurs"] = " ".join(occ)
        elif u == "REDEFINES":
            i += 1
            if i < len(words):
                item["redefines"] = words[i]
                i += 1
        else:
            i += 1
    return item


# ------------------------------------------------------- PROCEDURE (CST builder)
def split_paragraph_units(tokens):
    """Split procedure body into (header_tokens, body_tokens) paragraph units.

    A paragraph header is a period-terminated line whose tokens contain no
    statement verb (typically an AREA-A paragraph/section name on its own line).
    """
    line_groups = []
    for t in tokens:
        if line_groups and line_groups[-1][0] == t["line"]:
            line_groups[-1][1].append(t)
        else:
            line_groups.append((t["line"], [t]))

    area_a = any(t["col"] <= 11 for t in tokens)
    verbset = STATEMENT_VERBS | STRUCTURAL
    units = []  # [head_tokens, body_tokens]
    for _, utoks in line_groups:
        core = [t for t in utoks if t["type"] != "period"]
        ends_period = utoks[-1]["type"] == "period"
        has_verb = any(t["text"].upper() in verbset for t in core)
        header_like = ends_period and core and not has_verb and \
            (core[0]["col"] <= 11 if area_a else len(core) <= 4)
        if header_like or not units:
            units.append([utoks if header_like else [], []])
        if not header_like:
            units[-1][1].extend(utoks)
    return [(h, b) for h, b in units]


def build_procedure(header, body):
    units = split_paragraph_units(body)
    cst_children, ast_children = [], []
    for head, stmt_tokens in units:
        hw = words_of(head)
        is_section = any(w.upper() == "SECTION" for w in hw)
        name = " ".join(w for w in hw if w.upper() not in ("SECTION",))
        para_type = "section" if is_section else "paragraph"
        if not hw and not stmt_tokens:
            continue
        stmt_nodes = parse_statements(stmt_tokens)
        ast_stmts = [_ast_stmt(s) for s in stmt_nodes]
        cst_children.append({"type": para_type, "name": name or "(anonymous)",
                             "tokens": head, "children": stmt_nodes})
        ast_children.append({"type": para_type, "name": name or "(anonymous)",
                             "statements": ast_stmts})
    ast = {"type": "procedure_division",
           "using": words_of(header)[2:] if len(header) > 2 else [],
           "children": ast_children}
    return cst_children, ast


class _Container:
    __slots__ = ("kind", "node", "phase", "branch", "lists")

    def __init__(self, kind, node, lists):
        self.kind = kind          # root|if|evaluate|when|perform
        self.node = node
        self.phase = "condition" if kind in ("if", "evaluate", "when") else "body"
        self.branch = "then"      # for if
        self.lists = lists        # used for root/perform containers


def _snode(type_, tokens):
    return {"type": type_, "tokens": list(tokens), "children": [],
            "condition": [], "else_children": [], "branches": []}


def parse_statements(tokens):
    """Parse one paragraph body into a list of CST statement nodes."""
    root = _snode("paragraph_body", [])
    stack = [_Container("root", root, {"body": root["children"]})]
    buf = []
    pending_perform_node = None   # PERFORM waiting to learn block vs statement form

    def top():
        return stack[-1]

    def active_list():
        c = top()
        if c.kind == "if":
            return c.node["children"] if c.branch == "then" else c.node["else_children"]
        if c.kind == "when":
            return c.node["children"]
        if c.kind == "evaluate":
            return c.node["branches"]
        return c.lists["body"]

    def flush(period=None):
        nonlocal buf
        if not buf:
            return
        v = buf[0]["text"].upper()
        node_tokens = buf + ([period] if period else [])
        node = _snode(v.lower() + "_statement", node_tokens)
        node["verb"] = v
        active_list().append(node)
        buf = []

    i, n = 0, len(tokens)
    while i < n:
        t = tokens[i]
        u = t["text"].upper()
        c = top()

        if t["type"] == "comment":
            i += 1
            continue

        if t["type"] == "period":
            if buf:
                flush(t)
            elif pending_perform_node is not None:
                pending_perform_node["tokens"].append(t)  # statement-form PERFORM.
                active_list().append(pending_perform_node)
                pending_perform_node = None
            elif c.kind == "root" and c.lists["body"]:
                c.lists["body"][-1]["tokens"].append(t)  # stray '.' -> last stmt
            else:
                c.node["tokens"].append(t)  # block terminator period (END-IF.)
            i += 1
            continue

        if t["type"] == "punctuation":
            if buf:
                buf.append(t)
            elif pending_perform_node is not None:
                pending_perform_node["tokens"].append(t)
            else:
                c.node["tokens"].append(t)
            i += 1
            continue

        # structural keywords ------------------------------------------
        if u == "THEN" and not buf and c.phase == "condition":
            c.phase = "body"
            c.node["tokens"].append(t)
            i += 1
            continue

        if u == "ELSE" and c.kind == "if":
            flush()
            c.branch = "else"
            c.node["tokens"].append(t)
            i += 1
            continue

        if u == "END-IF" and c.kind == "if":
            flush()
            stack.pop()
            c.node["tokens"].append(t)
            i += 1
            continue

        if u == "WHEN" and c.kind in ("evaluate", "when"):
            flush()          # WHEN terminates the previous branch statement
            while stack and top().kind == "when":
                stack.pop()
            if top().kind != "evaluate":
                i += 1
                continue
            branch = _snode("when", [t])
            top().node["branches"].append(branch)
            stack.append(_Container("when", branch, {}))
            i += 1
            continue

        if u == "END-EVALUATE" and c.kind in ("evaluate", "when"):
            flush()
            while stack and top().kind == "when":
                stack.pop()
            c = top()
            stack.pop()
            c.node["tokens"].append(t)
            i += 1
            continue

        if u == "END-PERFORM":
            flush()
            if c.kind == "perform":
                stack.pop()
                c.node["tokens"].append(t)
            elif pending_perform_node is not None:
                pending_perform_node["tokens"].append(t)
                active_list().append(pending_perform_node)
                pending_perform_node = None
            i += 1
            continue

        # pending PERFORM: header operands vs inline body --------------
        if pending_perform_node is not None and not buf:
            if u in STATEMENT_VERBS:
                # inline PERFORM body begins: promote pending node to a block
                node = pending_perform_node
                pending_perform_node = None
                active_list().append(node)
                stack.append(_Container("perform", node, {"body": node["children"]}))
                continue           # re-process this verb inside the PERFORM block
            pending_perform_node["tokens"].append(t)
            i += 1
            continue

        # block-opening verbs: IF / EVALUATE / PERFORM ------------------
        if not buf and pending_perform_node is None and u in ("IF", "EVALUATE"):
            if c.phase == "condition":
                c.phase = "body"
            node = _snode(u.lower() + "_statement", [t])
            node["verb"] = u
            active_list().append(node)
            stack.append(_Container("if" if u == "IF" else "evaluate", node, {}))
            i += 1
            continue

        if not buf and pending_perform_node is None and u == "PERFORM":
            if c.phase == "condition":
                c.phase = "body"
            node = _snode("perform_statement", [t])
            node["verb"] = "PERFORM"
            pending_perform_node = node   # block form only if a verb follows
            i += 1
            continue

        # condition collection inside open blocks -----------------------
        if not buf and c.phase == "condition":
            if u in STATEMENT_VERBS:
                c.phase = "body"       # fall through: starts a nested statement
            elif u in STRUCTURAL:
                c.node["tokens"].append(t)
                i += 1
                continue
            else:
                c.node["condition"].append(t)
                c.node["tokens"].append(t)
                i += 1
                continue

        buf.append(t)
        i += 1

    flush()
    if pending_perform_node is not None:  # unterminated PERFORM at paragraph end
        active_list().append(pending_perform_node)
        pending_perform_node = None
    return root["children"]


# ------------------------------------------------------- CST -> AST
def _ast_stmt(node):
    verb = node.get("verb") or (node["tokens"][0]["text"].upper() if node["tokens"] else "UNKNOWN")
    operands = [t["text"] for t in node["tokens"]
                if t["type"] not in ("period",) and not (t["type"] == "punctuation"
                                                         and t["text"] in ".,;:")]
    # drop the verb word and structural keywords from operands
    structural = {"ELSE", "END-IF", "END-EVALUATE", "END-PERFORM", "THEN"}
    clean = []
    for text in operands[1:]:
        if text.upper() in structural:
            continue
        clean.append(text)
    out = {"type": verb.lower().replace("-", "_"), "verb": verb, "operands": clean}
    if verb == "IF":
        out["condition"] = [t["text"] for t in node["condition"]]
        out["then"] = [_ast_stmt(s) for s in node["children"]]
        out["else"] = [_ast_stmt(s) for s in node["else_children"]]
        return out
    if verb == "EVALUATE":
        out["subject"] = [t["text"] for t in node["condition"]]
        out["branches"] = []
        for b in node["branches"]:
            out["branches"].append({
                "type": "when",
                "condition": [t["text"] for t in b["condition"]],
                "then": [_ast_stmt(s) for s in b["children"]],
            })
        return out
    if node.get("children"):
        out["body"] = [_ast_stmt(s) for s in node["children"]]
    return out


# ------------------------------------------------------- entry point
def build_trees(source):
    tokens = tokenize(source)
    divisions = split_divisions(tokens)
    cst_children, ast_children = [], []
    program_name = ""
    for name, header, body in divisions:
        if name == "IDENTIFICATION":
            p_cst, p_ast = build_identification(body)
            for ch in p_ast["children"]:
                if ch.get("type") == "program_identification":
                    program_name = ch["name"]
        elif name == "ENVIRONMENT":
            p_cst, p_ast = build_environment(body)
        elif name == "DATA":
            p_cst, p_ast = build_data(body)
        elif name == "PROCEDURE":
            p_cst, p_ast = build_procedure(header, body)
        else:
            p_cst = [{"type": "paragraph", "tokens": p, "children": []}
                     for p in group_paragraphs(body)]
            p_ast = {"type": "remarks", "children": []}
        cst_children.append({"type": name.lower() + "_division",
                             "tokens": header, "children": p_cst})
        ast_children.append(p_ast)
    cst = {"type": "source_file", "language": "cobol", "children": cst_children,
           "token_count": len([t for t in tokens if t["type"] != "comment"]),
           "comments": [tok("comment", t["text"], t["line"], t["col"])
                        for t in tokens if t["type"] == "comment"]}
    ast = {"type": "program", "language": "cobol", "name": program_name or "(unknown)",
           "children": ast_children}
    return cst, ast
