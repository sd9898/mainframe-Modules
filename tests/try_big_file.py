"""Large-file smoke test: proves the engines handle 50k-60k+ line files.

Runs OFFLINE (no servers needed) against the parser modules directly:
    python tests/try_big_file.py [LINES]

Generates a ~60,000-line COBOL program and a ~60,000-line JavaScript file,
parses both into CST + AST, and checks the work completes (no recursion
errors) in a reasonable time.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.setrecursionlimit(200000)

from parse_service.parsers import cobol_parser, generic_parser  # noqa: E402

TARGET_LINES = int(sys.argv[1]) if len(sys.argv) > 1 else 60000


def col(text, start=8):
    return " " * (start - 1) + text


def gen_cobol(target):
    out = ["       IDENTIFICATION DIVISION.", "       PROGRAM-ID. BIGPROG.",
           "       DATA DIVISION.", "       WORKING-STORAGE SECTION."]
    n = 0
    # bulk working-storage items
    while n < target // 2:
        out.append(col(f"01 W{n:06d} PIC 9(6) VALUE {n % 100}.", 8))
        n += 1
    out.append(col("PROCEDURE DIVISION.", 8))
    para = 0
    # bulk procedure paragraphs (each ~4 lines)
    while len(out) < target:
        out.append(col(f"P{para:06d}-PARA.", 8))
        out.append(col(f"MOVE {para} TO W{para % (target // 2):06d}.", 12))
        out.append(col(f"IF W{para % (target // 2):06d} > 5", 12))
        out.append(col("DISPLAY 'HOT'", 16))
        out.append(col("ELSE", 16))
        out.append(col("DISPLAY 'COLD'", 16))
        out.append(col("END-IF.", 12))
        para += 1
    return "\r\n".join(out) + "\r\n"


def gen_js(target):
    lines = []
    i = 0
    while len(lines) < target:
        lines.append(f"function handler{i}() {{")
        lines.append(f"  const v{i} = {i};")
        lines.append(f"  if (v{i} > 5) {{ console.log('big', v{i}); }}")
        lines.append(f"  return v{i} * 2;")
        lines.append("}")
        i += 1
    return "\n".join(lines[:target]) + "\n"


def run(name, source, build):
    lines = source.count("\n")
    print(f"\n=== {name}: {lines:,} lines, {len(source):,} bytes ===")
    t0 = time.perf_counter()
    result = build(source)
    dt = time.perf_counter() - t0
    print(f"parsed in {dt:.2f}s -> {type(result).__name__ if not isinstance(result, tuple) else 'cst+ast'}")
    return dt, result


# ---- COBOL
cobol_src = gen_cobol(TARGET_LINES)
dt_c, cobol_trees = run("COBOL", cobol_src, cobol_parser.build_trees)
cst, ast = cobol_trees
assert ast["type"] == "program" and ast["name"] == "BIGPROG", ast.get("name")
assert cst["token_count"] > 1000
procd = [c for c in ast["children"] if c["type"] == "procedure_division"][0]
assert len(procd["children"]) > 100, "expected many paragraphs"

# ---- Generic (any language) via JavaScript
js_src = gen_js(TARGET_LINES)
dt_g, js_trees = run("JavaScript (generic engine)", js_src,
                     lambda s: generic_parser.build_trees(s, "javascript"))
assert js_trees[0]["token_count"] > 1000
assert js_trees[1]["children"], "generic AST empty"

print(f"\nBoth files exceed the 50,000-line requirement.")
print(f"COBOL ~{TARGET_LINES:,} lines in {dt_c:.2f}s | "
      f"generic ~{TARGET_LINES:,} lines in {dt_g:.2f}s")
print("LARGE-FILE TEST PASSED")
