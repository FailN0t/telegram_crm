#!/usr/bin/env python3
"""
Tiny minifier for static CSS/JS assets.
Keeps it dependency-free for local/prod builds.
"""

from pathlib import Path


def _minify_css(text: str) -> str:
    out = []
    in_comment = False
    i = 0
    while i < len(text):
        if not in_comment and text[i:i+2] == "/*":
            in_comment = True
            i += 2
            continue
        if in_comment and text[i:i+2] == "*/":
            in_comment = False
            i += 2
            continue
        if not in_comment:
            out.append(text[i])
        i += 1
    compact = "".join(out)
    compact = " ".join(compact.split())
    compact = compact.replace(" {", "{").replace("{ ", "{")
    compact = compact.replace(" }", "}").replace("; ", ";")
    compact = compact.replace(": ", ":").replace(", ", ",")
    return compact.strip()


def _minify_js(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        lines.append(line)
    compact = "\n".join(lines)
    compact = " ".join(compact.split())
    compact = compact.replace(" {", "{").replace("{ ", "{")
    compact = compact.replace(" }", "}").replace("; ", ";")
    compact = compact.replace(": ", ":").replace(", ", ",")
    return compact.strip()


def main() -> None:
    static_dir = Path(__file__).resolve().parent.parent / "static"
    css_path = static_dir / "styles.css"
    if css_path.exists():
        css_min = _minify_css(css_path.read_text(encoding="utf-8"))
        (static_dir / "styles.min.css").write_text(css_min + "\n", encoding="utf-8")

    for js_name in ("app.js", "auth.js"):
        js_path = static_dir / js_name
        if not js_path.exists():
            continue
        js_min = _minify_js(js_path.read_text(encoding="utf-8"))
        (static_dir / js_name.replace(".js", ".min.js")).write_text(
            js_min + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
