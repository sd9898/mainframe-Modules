# CST & AST Microservices (FastAPI)

Upload **any source file in any language** — COBOL, Python, JavaScript/TypeScript, C/C++, C#, Java, Go, Rust, Ruby, PHP, Swift, Kotlin, SQL, HTML/CSS, JSON/YAML, Bash, and anything else text-based — and get back its **Concrete Syntax Tree (CST)** and **Abstract Syntax Tree (AST)** through clean REST APIs.

It is built as small, independent **FastAPI microservices** so nothing gets complicated, and it handles **very large files (50,000–60,000+ lines)**.

```
                 +--------------------------+
   file upload -> |  gateway   :8000         |  POST /analyze (one-call pipeline)
                 +------------+-------------+
                              |
              +---------------+----------------+
              |                                |
   +----------v----------+          +----------v----------+
   | language-service    |          | parse-service       |
   | :8001               |          | :8002               |
   | POST /detect-language|          | POST /parse/cst     |
   | GET  /health        |          | POST /parse/ast     |
   +---------------------+          | POST /parse/both    |
                                    | POST /render        |
                                    | POST /obsidian      |
                                    +---------------------+
```

| Service | Port | Responsibility |
|---|---|---|
| **gateway** | 8000 | Single entry point, orchestrates the pipeline, proxies individual APIs |
| **language-service** | 8001 | Detects the file's language (extension + content heuristics) |
| **parse-service** | 8002 | Builds CST + AST for **any language** (dedicated COBOL & Python engines + a language-agnostic generic engine) and exports an **Obsidian** graph vault |

Each service has its own interactive docs: `http://127.0.0.1:8000/docs` (and `:8001/docs`, `:8002/docs`).

## Quick start (Windows)

```bat
pip install -r requirements.txt
start_all.bat
```

Or (Linux/macOS): `./start_all.sh`.

> No Docker required — services run directly with Uvicorn. To run a single service manually:
> `python -m uvicorn gateway.main:app --port 8000` (also `language_service.main:app` :8001, `parse_service.main:app` :8002).

Analyze a file end-to-end:

```powershell
curl.exe -X POST "http://127.0.0.1:8000/analyze" -F "file=@samples/HelloWorld.cbl"
```

```bash
curl -X POST http://127.0.0.1:8000/analyze -F file=@samples/HelloWorld.cbl
```

Response (trimmed):

```json
{
  "filename": "HelloWorld.cbl",
  "detection": {"language": "cobol", "confidence": 1.0, "method": "extension+content"},
  "cst":  {"type": "source_file", "children": [{"type": "identification_division", "tokens": [...], ...}]},
  "ast":  {"type": "program", "name": "HELLO", "children": [...]},
  "stats": {"tokens": 139, "cst_nodes": 220, "ast_nodes": 63}
}
```

Query flags on `/analyze`: `?include_cst=false` or `?include_ast=false` to request one tree only.

## API reference

### Gateway (`:8000`)
| Method | Path | Description |
|---|---|---|
| GET | `/` | service map |
| GET | `/health` | aggregate health of all services |
| POST | `/analyze` | file → detection **+** CST **+** AST (multipart `file`) |
| POST | `/detect-language` | proxied to language-service |
| POST | `/parse/cst`, `/parse/ast`, `/parse/both`, `/render` | proxied to parse-service (`language` form field: `auto` or explicit) |
| POST | `/obsidian`, `/obsidian/zip` | proxied to parse-service — Obsidian vault (JSON / downloadable zip) |

### Language service (`:8001`)
| Method | Path | Description |
|---|---|---|
| POST | `/detect-language` | multipart `file` **or** JSON `{"filename?", "content"}` → `{language, confidence, method, signals}` |
| GET | `/health` | liveness |

Detects: cobol, python, javascript, typescript, c, cpp, java, ruby, go, sql, shell,
plus mainframe artefacts — **jcl, bms (CICS maps), assembler, sort (DFSORT/JCL)**,
SQL DDL, and **BASIC, Perl, Lua, PHP**. A confidence floor prevents a single stray
keyword from misclassifying a file, and mainframe/known extensions are authoritative.

### Parse service (`:8002`)
| Method | Path | Description |
|---|---|---|
| POST | `/parse/cst` | file → Concrete Syntax Tree (every token, lossless) |
| POST | `/parse/ast` | file → Abstract Syntax Tree (semantic nodes only) |
| POST | `/parse/both` | file → `{cst, ast, stats, parse_error}` |
| POST | `/render` | file → ASCII tree (`tree=ast` or `tree=cst`) |
| POST | `/obsidian` | file → **Obsidian vault** JSON: `{files, mermaid, node_count}` |
| POST | `/obsidian/zip` | file → downloadable `.zip` Obsidian vault (open as a vault) |

Form fields: `file` (required), `language` (`auto`/`cobol`/`python`/anything→generic),
and for `/obsidian*`: `tree` (`ast`/`cst`), `max_nodes` (cap for huge trees).

## Parsing engines

- **COBOL** — purpose-built parser (`parse_service/parsers/cobol_parser.py`):
  fixed- **and** free-format, all four divisions, `PROGRAM-ID`, `SELECT/ASSIGN`
  file control, level-number data items with `PIC/USAGE/VALUE/OCCURS` and group
  nesting, paragraphs/sections, and statements incl. `IF/ELSE/END-IF`,
  `EVALUATE/WHEN/END-EVALUATE`, `PERFORM` (statement & inline block form),
  `CALL ... USING`, arithmetic and `MOVE`.
  *CST* keeps every token (`keyword`, `identifier`, `literal`, `period`, …) with
  line/col info; *AST* exposes `program → divisions → paragraphs → typed
  statements {verb, operands, condition, then/else, branches}`.
- **Python** — standard library only: `ast` module for the AST, `tokenize` for a
  fully lossless CST.
- **Generic engine (any language)** — used for everything without a dedicated
  parser (JavaScript, TypeScript, C, C++, C#, Java, Go, Rust, Ruby, PHP, Swift,
  Kotlin, SQL, HTML, CSS, JSON, YAML, Bash, …): a language-agnostic tokenizer
  builds a per-line CST (every token, with column info) and an
  indentation/brace-nested AST with statement classification
  (function/class/conditional/loop/import/…). Pass `language=auto` or an
  explicit name; unknown names safely fall back to the generic engine.

## Obsidian visualization

Every tree can be exported as an **[Obsidian](https://obsidian.md) vault** so the
syntax tree becomes a navigable, visual **graph of nodes**:

- `00-index.md` — program overview, node count and a native **Mermaid** diagram
  (Obsidian renders Mermaid out of the box — an instant tree picture).
- `nodes/<id>-<label>.md` — one note per tree node, linked to its parent and
  children with `[[wikilinks]]`. Open the vault's **Graph view** to explore the
  whole CST/AST as connected nodes.

```powershell
# get the vault as JSON (map of path -> markdown)
curl.exe -X POST http://127.0.0.1:8000/obsidian -F file=@samples/HelloWorld.cbl -F tree=ast

# download a ready-to-open .zip vault
curl.exe -X POST http://127.0.0.1:8000/obsidian/zip -F file=@samples/HelloWorld.cbl -o vault.zip
```

`max_nodes` bounds the export for very large files (the index notes when a tree
was truncated). To build a combined multi-language vault from a whole repo, run
`python tests/try_carddemo.py --vault` (writes `obsidian_vault/carddemo/`).

## Tests

```bat
python tests\try_cobol.py    :: offline parser unit checks (no servers needed)
python tests\try_api.py      :: end-to-end API tests (services must be running)
python tests\try_big_file.py :: 60,000-line scale test
python tests\try_carddemo.py --vault :: sweep a real multi-language mainframe repo
python tests\try_repo.py <dir> --vault :: generic sweep of ANY cloned repo (used to
                                          :: validate ACAS, GNUCobol-Samples, …)
```

## Project layout

```
gateway/                API gateway (:8000)
language_service/       language detection microservice (:8001)
parse_service/          CST/AST parse microservice (:8002)
  parsers/              cobol_parser.py, python_parser.py, generic_parser.py
  obsidian.py           AST/CST -> Obsidian vault (interlinked notes + Mermaid)
samples/                HelloWorld.cbl, demo.py, app.js
tests/                  try_cobol.py (unit), try_api.py (e2e), try_big_file.py (60k lines),
                        try_carddemo.py (real-repo sweep + Obsidian vault)
start_all.bat / .sh     one-command local launch
```

## Notes & limitations

- **Any language**: files with no dedicated grammar are parsed by the generic
  engine, so uploads never fail due to an unsupported language.
- **Large files**: tested at 60,000 lines; the max upload is 200 MB (well above
  50k–60k-line files). Deep-tree helpers are iterative / recursion-limited.
- COBOL scope: common structured COBOL (see engines). Old-style un-terminated
  `IF` blocks (no `END-IF`) are parsed as flat statements.
- No Docker needed — run with Uvicorn (see Quick start). Each service is
  stateless: to scale, run replicas behind any load balancer and point the
  gateway at them with `LANGUAGE_SERVICE_URL` / `PARSE_SERVICE_URL`.
