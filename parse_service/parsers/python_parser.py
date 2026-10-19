"""Python parser: CST via the tokenize module, AST via the built-in ast module."""

import ast
import io
import tokenize as pytokenize


def _tok_name(tok_type):
    try:
        return pytokenize.tok_name[tok_type]
    except KeyError:
        return str(tok_type)


def build_cst(source):
    """Concrete Syntax Tree: every token (keywords, operators, comments, NL)."""
    root = {"type": "file", "language": "python", "lines": [], "children": []}
    line_index = {}
    try:
        reader = io.StringIO(source).readline
        for t in pytokenize.generate_tokens(reader):
            node = {
                "type": "token",
                "token_type": _tok_name(t.type),
                "text": t.string,
                "line": t.start[0],
                "col": t.start[1],
            }
            if node["token_type"] in ("NL", "NEWLINE"):
                node["type"] = "newline"
            if node["token_type"] == "INDENT":
                node["type"] = "indent"
            if node["token_type"] == "DEDENT":
                node["type"] = "dedent"
            idx = node["line"]
            if idx not in line_index:
                line_node = {"type": "line", "line": idx, "children": []}
                line_index[idx] = line_node
                root["children"].append(line_node)
            if node["token_type"] != "ENDMARKER":
                line_index[idx]["children"].append(node)
    except pytokenize.TokenError as e:
        root["tokenize_error"] = str(e)
    root["token_count"] = sum(len(l["children"]) for l in root["children"])
    return root


def _node_to_dict(node):
    """Recursively convert an ast.AST into a clean dict tree."""
    out = {"type": type(node).__name__}
    # keep small scalar attributes (names, operators, constants)
    for field in getattr(node, "_attributes", []):
        if field in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            out.setdefault("loc", {})[field] = getattr(node, field)
        elif field == "ctx":
            out["ctx"] = type(getattr(node, field)).__name__
    for field in getattr(node, "_fields", []):
        value = getattr(node, field)
        if isinstance(value, ast.AST):
            out.setdefault(field, []).append(_node_to_dict(value))
        elif isinstance(value, list):
            items = [_node_to_dict(v) if isinstance(v, ast.AST) else v for v in value]
            if items:
                out[field] = items
        elif value is not None and value != ():
            out[field] = value
    return out


def build_ast(source):
    """Abstract Syntax Tree from CPython's own parser."""
    tree = ast.parse(source)
    return _node_to_dict(tree)


def build_trees(source):
    cst = build_cst(source)
    try:
        ast_tree = build_ast(source)
        parse_error = None
    except SyntaxError as e:
        ast_tree = None
        parse_error = {"message": e.msg, "line": e.lineno, "offset": e.offset}
    return cst, ast_tree, parse_error
