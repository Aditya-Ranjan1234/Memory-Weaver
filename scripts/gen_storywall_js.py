from __future__ import annotations

import json
from pathlib import Path


def js_str(s: str) -> str:
    # Keep index.html ASCII-safe: story content already uses \\u escapes.
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", "\\n")
    )


def main() -> None:
    p = Path("scripts/stories.json")
    raw = p.read_bytes()
    # PowerShell redirection often writes UTF-16 with BOM.
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16")
    else:
        text = raw.decode("utf-8")
    items = json.loads(text)
    print("const storyWallCards = [")
    for it in items:
        tags = ["multilingual"] + [t for t in it.get("tags", []) if t and t != "story"]
        obj = (
            "  { "
            f'title: "{js_str(it["title"])}", '
            'person: "Family", '
            f'lang: "{js_str(it.get("lang",""))}", '
            f"tags: {json.dumps(tags)}, "
            f'body: "{js_str(it.get("body",""))}" '
            "},"
        )
        print(obj)
    print("];")


if __name__ == "__main__":
    main()
