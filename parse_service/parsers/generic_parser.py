"""Generic parser fallback for any text-based language.

Builds a CST of every token per line and an indentation/brace-based AST.
Used for languages without a dedicated parser (JS, C, Java, Ruby, ...).
"""

import re

TOKEN_RE = re.compile(
    r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'  # strings
    r"|//[^\n]*|#[^\n]*"                                          # comments
    r"|\b\d+(?:\.\d+)?\b"                                          # numbers
    r"|[A-Za-z_$@][\w$-]*"                                         # identifiers/keywords
    r"|[{}()\[\];,.<>+\-*/%=&|!?:~^]+"                             # operators
)


def lex(line):
    tokens = []
    for m in TOKEN_RE.finditer(line):
        text = m.group(0)
        if text.startswith(('"', "'", "`")):
            ttype = "string"
        elif text.startswith(("//", "#")):
            ttype = "comment"
        elif re.match(r"^\d", text):
            ttype = "number"
        elif re.match(r"^[A-Za-z_$@]", text):
            ttype = "word"
        else:
            ttype = "operator"
        tokens.append({"type": "token", "token_type": ttype, "text": text,
                       "col": m.start() + 1})
    return tokens


def _indent_of(line):
    return len(line) - len(line.lstrip())


def build_trees(source, language="generic"):
    lines = source.splitlines()

    # ---------------- CST: every line, every token, lossless
    cst_children = []
    for ln, raw in enumerate(lines, 1):
        toks = lex(raw)
        node = {"type": "line", "line": ln, "indent": _indent_of(raw),
                "raw": raw, "children": toks}
        cst_children.append(node)
    cst = {"type": "source_file", "language": language, "children": cst_children,
           "token_count": sum(len(n["children"]) for n in cst_children)}

    # ---------------- AST: structural nesting by indentation / braces
    ast_root = {"type": "source_file", "language": language, "children": []}
    stack = [(-1, ast_root)]  # (indent, node)
    brace_mode = any("{" in l for l in lines[:200])

    for ln, raw in enumerate(lines, 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")) and not stripped.startswith("*/"):
            continue
        indent = _indent_of(raw)
        opens_block = stripped.endswith(("{", ":")) or stripped.endswith("(")
        node = {
            "type": _classify(stripped),
            "text": stripped.rstrip("{ ").rstrip(";") if brace_mode else stripped.rstrip(":").rstrip("{"),
            "line": ln,
            "children": [],
        }
        if brace_mode and stripped.startswith("}"):
            # closing line: pop to the level that opened
            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()
            continue
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        stack[-1][1]["children"].append(node)
        if opens_block:
            stack.append((indent, node))

    return cst, ast_root


KEYWORD_KINDS = [
    (re.compile(r"^\s*(function|def|func|sub|procedure|PARAGRAPH)\b", re.I), "function_definition"),
    (re.compile(r"^\s*(class|struct|interface|enum|PROGRAM-ID|IDENTIFICATION)\b", re.I), "type_definition"),
    (re.compile(r"^\s*(if|elif|else|ELSE|IF)\b", re.I), "conditional"),
    (re.compile(r"^\s*(for|while|loop|PERFORM|do|REPEAT)\b", re.I), "loop"),
    (re.compile(r"^\s*(return|EXIT|GOBE)\b", re.I), "return"),
    (re.compile(r"^\s*(import|include|uses|USE|requires)\b", re.I), "import"),
    (re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE)\b", re.I), "query"),
]


def _classify(stripped):
    for pattern, kind in KEYWORD_KINDS:
        if pattern.match(stripped):
            return kind
    return "statement"
