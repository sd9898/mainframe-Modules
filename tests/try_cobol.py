"""Offline smoke test for the COBOL parser (no servers needed).

Run:  python tests/try_cobol.py
Checks the AST structure of samples/HelloWorld.cbl and prints both trees.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parse_service.parsers import cobol_parser  # noqa: E402

HERE = os.path.dirname(__file__)
SRC = open(os.path.join(HERE, "..", "samples", "HelloWorld.cbl"),
           encoding="utf-8").read()

cst, ast = cobol_parser.build_trees(SRC)

print("=== AST ===")
print(json.dumps(ast, indent=1))
print("\n=== CST (divisions only, truncated) ===")
print(json.dumps({k: v for k, v in cst.items() if k != "children"}, indent=1))
for div in cst["children"]:
    print(f"division={div['type']} header_tokens={' '.join(t['text'] for t in div['tokens'])} "
          f"children={len(div['children'])}")

# --- structural assertions
assert ast["name"] == "HELLO", ast["name"]
divs = {c["type"]: c for c in ast["children"]}
assert "identification_division" in divs
assert "environment_division" in divs
assert "data_division" in divs
assert "procedure_division" in divs

env = divs["environment_division"]["children"]
sel = [c for c in env if c["type"] == "file_selection"]
assert sel and sel[0]["file_name"] == "EMP-FILE", sel

data = divs["data_division"]["children"]
ws = [s for s in data if s["type"] == "working_storage_section"][0]
items = [c for c in ws["children"] if c["type"] == "data_item"]
pics = {i["name"]: i.get("picture") for i in items}
assert pics.get("WS-COUNTER") == "9(3)", pics
flags = [i for i in items if i["name"] == "WS-FLAGS"][0]
assert [c["name"] for c in flags["children"]] == ["WS-FLAG-A", "WS-FLAG-B"], flags
assert flags["children"][0]["value"] == '"N"', flags["children"][0]

proc = divs["procedure_division"]["children"]
paras = {p["name"]: p for p in proc}
assert "MAIN-PARA" in paras and "GREET-PARA" in paras, list(paras)
stmts = paras["MAIN-PARA"]["statements"]
verbs = [s["verb"] for s in stmts]
assert verbs == ["MOVE", "ADD", "IF", "EVALUATE", "PERFORM", "CALL", "STOP"], verbs

if_st = [s for s in stmts if s["verb"] == "IF"][0]
assert "WS-COUNTER" in " ".join(if_st["condition"]), if_st["condition"]
assert if_st["then"][0]["verb"] == "DISPLAY", if_st["then"]
assert if_st["else"][0]["verb"] == "DISPLAY", if_st["else"]

ev = [s for s in stmts if s["verb"] == "EVALUATE"][0]
assert len(ev["branches"]) == 2, ev
assert ev["branches"][0]["condition"] == ['"Y"'], ev["branches"][0]

pf = [s for s in stmts if s["verb"] == "PERFORM"][0]
assert "GREET-PARA" in pf["operands"], pf

# CST completeness: every source token text present in CST
cst_blob = json.dumps(cst).replace('\\"', '"')
for w in SRC.split():
    assert w.strip(".") in cst_blob or w.strip() == ".", f"missing {w}"

print("\nALL COBOL PARSER CHECKS PASSED")
