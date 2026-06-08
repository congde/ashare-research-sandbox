from pathlib import Path
import re
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
PUBLISHABLE_CHAPTERS = (
    ROOT / "docs/v2/01-第一个委托.md",
    ROOT / "docs/v2/04-调研与整理.md",
    ROOT / "docs/v2/09-Skills工作流.md",
    ROOT / "docs/v2/14-Bug与热修复.md",
    ROOT / "docs/v2/20-Playbook与推广.md",
)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def local_target(source: Path, raw_target: str) -> Optional[Path]:
    if raw_target.startswith(("http://", "https://", "#")):
        return None
    target = raw_target.split("#", 1)[0]
    return (source.parent / target).resolve()


def main() -> int:
    errors: list[str] = []

    for chapter in PUBLISHABLE_CHAPTERS:
        if not chapter.is_file():
            errors.append(f"missing publishable chapter: {chapter.relative_to(ROOT)}")
            continue

        text = chapter.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = local_target(chapter, raw_target)
            if target is not None and not target.exists():
                errors.append(
                    f"{chapter.relative_to(ROOT)} links to missing {raw_target}"
                )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1

    print("publishable chapter links are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
