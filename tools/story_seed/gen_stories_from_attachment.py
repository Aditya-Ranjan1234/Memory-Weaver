from __future__ import annotations

import re
import json
from pathlib import Path


ATTACHMENT = Path(
    r"C:\Users\OMEN\.codex\attachments\aef75ac0-99e7-4182-9b07-5f8928ec8a61\pasted-text.txt"
)


def fix_mojibake_to_unicode_escapes(text_bytes: bytes) -> str:
    """
    The attachment contains UTF-8 bytes that got mojibake-decoded. This recovers
    the intended Unicode but keeps the output ASCII-safe using \\u escapes.
    """
    s = text_bytes.decode("utf-8", "surrogateescape")
    # Convert mojibake chars back to original bytes via latin1, then decode as utf-8.
    return s.encode("latin1", "backslashreplace").decode("utf-8", "replace")


def parse_stories(md: str) -> list[dict]:
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n---\n", md)
    items: list[dict] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Note: the recovered text uses ASCII-safe escapes like "\\u2014" instead of the literal em dash.
        m = re.search(
            r"^##\s*(\d+)\.\s*\*\*(.+?)\*\*(?:\s*\\u2014\s*\*(.+?)\*)?\s*$",
            part,
            re.M,
        )
        if not m:
            continue

        num = int(m.group(1))
        title_raw = m.group(2).strip()
        subtitle = (m.group(3) or "").strip()

        # Body is everything after the heading line.
        lines = part.replace("\r\n", "\n").replace("\r", "\n").splitlines()
        heading_idx = None
        for i, line in enumerate(lines):
            if line.strip().startswith(f"## {num}."):
                heading_idx = i
                break
        body_lines = []
        if heading_idx is not None:
            body_lines = lines[heading_idx + 1 :]
        body = "\n".join(body_lines).strip()

        lang = ""
        ml = re.search(r"\(([^)]+)\)", title_raw)
        if ml:
            lang = ml.group(1).strip()

        clean_title = re.sub(r"\s*\([^)]*\)\s*", " ", title_raw)
        clean_title = re.sub(r"\s+", " ", clean_title).strip()

        tags = {"story"}
        st = subtitle.lower()
        if "food" in st or "tradition" in st:
            tags.update({"food", "tradition"})
        if "festival" in st:
            tags.add("festival")
        if "family" in st:
            tags.add("family")
        if "marriage" in st:
            tags.add("marriage")
        if "tragedy" in st or "crisis" in st:
            tags.update({"crisis", "community"})
        if "salary" in clean_title.lower() or "job" in clean_title.lower():
            tags.update({"work", "family"})

        items.append(
            {
                "n": num,
                "title": clean_title,
                "lang": lang or "English",
                "subtitle": subtitle,
                "body": body,
                "tags": sorted(tags),
            }
        )

    items.sort(key=lambda x: x["n"])
    return items


def main() -> None:
    md = fix_mojibake_to_unicode_escapes(ATTACHMENT.read_bytes())
    items = parse_stories(md)
    print(json.dumps(items, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
