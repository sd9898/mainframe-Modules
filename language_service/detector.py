"""Language detection logic for source files.

Combines extension hints with content-based scoring so that files
without a useful extension (or pasted content) can still be classified.
"""

import re

# extension -> language
EXTENSION_MAP = {
    ".cbl": "cobol", ".cob": "cobol", ".cpy": "cobol",
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".java": "java",
    ".rb": "ruby", ".go": "go", ".rs": "rust",
    ".html": "html", ".css": "css", ".json": "json", ".xml": "xml",
    ".sql": "sql", ".sh": "shell", ".bat": "batch", ".ps1": "powershell",
}

# (regex, weight) signals per language
CONTENT_SIGNALS = {
    "cobol": [
        (r"\bIDENTIFICATION\s+DIVISION\b", 10),
        (r"\bPROGRAM[- ]ID\b", 8),
        (r"\bDIVISION\b", 3),
        (r"\bWORKING-STORAGE\b", 6),
        (r"\bPIC\s+[TX9]", 5),
        (r"\bPERFORM\b", 3),
        (r"\bDISPLAY\b", 2),
        (r"\bEND-IF\b", 4),
        (r"\bEVALUATE\b", 2),
        (r"\bGOBE\b", 5),
        (r"\bUSAGE\b", 2),
        (r"^\s*\d{6}", 3),  # fixed-format sequence numbers
    ],
    "python": [
        (r"^\s*def\s+\w+\s*\(", 6),
        (r"^\s*import\s+\w+", 4),
        (r"^\s*from\s+\w+\s+import\b", 5),
        (r"\bclass\s+\w+\s*[(:]", 4),
        (r"__name__\s*==", 6),
        (r"^\s*self\.\w+", 4),
        (r"\bf\s*[\"']", 2),
        (r"^\s*print\s*\(", 2),
    ],
    "javascript": [
        (r"\bfunction\s*\w*\s*\(", 5),
        (r"\b(const|let|var)\s+\w+\s*=", 4),
        (r"=>", 3),
        (r"\bconsole\.log\b", 4),
        (r"\brequire\s*\(", 3),
        (r"\bdocument\.\w+", 3),
    ],
    "c": [
        (r"#include\s*[<\"]", 8),
        (r"\bint\s+main\s*\(", 6),
        (r"\bprintf\s*\(", 4),
        (r"\bmalloc\s*\(", 3),
        (r"\bchar\s*\*", 3),
    ],
    "cpp": [
        (r"#include\s*<(iostream|vector|string)", 8),
        (r"\bstd::", 5),
        (r"\bcout\s*<<", 6),
        (r"\btemplate\s*<", 5),
    ],
    "java": [
        (r"\bpublic\s+(static\s+)?(void|class)\b", 6),
        (r"\bSystem\.out\.print", 6),
        (r"\bimport\s+java\.", 6),
        (r"@Override", 4),
    ],
    "ruby": [(r"\bdef\s+\w+\s*$", 4), (r"\bputs\b", 4), (r"\bend\s*$", 2)],
    "go": [(r"\bfunc\s+\w*\(", 6), (r"\bpackage\s+main\b", 6), (r"\bfmt\.Print", 5)],
    "sql": [(r"\bSELECT\b.+?\bFROM\b", 6), (r"\bCREATE\s+TABLE\b", 6), (r"\bINSERT\s+INTO\b", 5)],
    "shell": [(r"^#!.*sh", 8), (r"\becho\s+[\"$]", 3)],
}


def detect(filename: str | None, content: str) -> dict:
    """Return language, confidence (0..1), method and matched signals."""
    text = content or ""
    sample = text[:200_000]

    ext_lang = None
    if filename and "." in filename:
        ext_lang = EXTENSION_MAP.get("." + filename.rsplit(".", 1)[-1].lower())

    scores: dict[str, int] = {}
    for lang, signals in CONTENT_SIGNALS.items():
        total = 0
        for pattern, weight in signals:
            if re.search(pattern, sample, re.IGNORECASE | re.MULTILINE):
                total += weight
        if total:
            scores[lang] = total

    content_lang = max(scores, key=scores.get) if scores else None
    max_score = scores.get(content_lang, 0)

    # combine extension + content
    if content_lang and ext_lang and content_lang == ext_lang:
        language, method, confidence = content_lang, "extension+content", min(1.0, 0.7 + max_score / 40)
    elif ext_lang and (not content_lang or max_score < 8):
        language, method, confidence = ext_lang, "extension", 0.6
    elif content_lang:
        language, method, confidence = content_lang, "content", min(1.0, 0.35 + max_score / 40)
    elif ext_lang:
        language, method, confidence = ext_lang, "extension", 0.5
    else:
        language, method, confidence = "generic", "none", 0.1

    return {
        "language": language,
        "confidence": round(confidence, 3),
        "method": method,
        "signals": {
            lang: round(score / max(max_score, 1), 3) for lang, score in sorted(
                scores.items(), key=lambda kv: -kv[1])[:4]
        },
        "supported_parsers": ["cobol", "python", "generic"],
    }
