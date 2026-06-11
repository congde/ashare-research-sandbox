"""Add a short introduction before figures that start without prose context."""

from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
CHAPTER = re.compile(r"^(0[0-9]|1[0-9]|20)-")
IMAGE = re.compile(r"^!\[[^\]]+\]\([^)]+\)\s*$")
CAPTION = re.compile(r"^\*\*图\s+(\d+)-(\d+)[　 ]+(.+?)\*\*\s*$")
NON_PROSE = re.compile(r"^(?:#|!\[|\*\*图|\*\*表|```|\|)")


def normalize(path: Path) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        if IMAGE.match(lines[index]):
            previous = len(output) - 1
            while previous >= 0 and not output[previous].strip():
                previous -= 1
            needs_intro = previous < 0 or NON_PROSE.match(output[previous])

            cursor = index + 1
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            caption = CAPTION.match(lines[cursor]) if cursor < len(lines) else None
            if needs_intro and caption:
                if output and output[-1].strip():
                    output.append("")
                output.append(
                    f"先看图 {caption.group(1)}-{caption.group(2)}。"
                    f"它把“{caption.group(3)}”放进一张流程图，"
                    "后续步骤会逐项展开其中的判断。"
                )
                output.append("")
        output.append(lines[index])
        index += 1
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    for path in sorted((ROOT / "docs/v2").glob("*.md")):
        if CHAPTER.match(path.name) and "修订对照" not in path.name:
            normalize(path)
    print("normalized figure introductions for chapters 00-20")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
