#!/usr/bin/env python3
"""Build a portable ZIP with SKILL.md at the archive root."""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


EXCLUDED_NAMES = {".DS_Store", "__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--skill-dir",
        type=Path,
        default=repo_root / "ashare-fundamentals",
    )
    parser.add_argument("--output-dir", type=Path, default=repo_root / "dist")
    return parser.parse_args()


def split_skill(skill_file: Path) -> tuple[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.DOTALL)
    if not match:
        raise ValueError(f"invalid frontmatter in {skill_file}")
    return match.group(1), match.group(2)


def field(frontmatter: str, name: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}:\s*['\"]?(.*?)['\"]?\s*$", frontmatter)
    if not match:
        raise ValueError(f"missing {name} in SKILL.md")
    return match.group(1)


def read_version(skill_file: Path) -> str:
    frontmatter, _ = split_skill(skill_file)
    version = field(frontmatter, "version")
    match = re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    if not match:
        raise ValueError(f"semantic version is missing from {skill_file}")
    return version


def workbuddy_skill(skill_file: Path) -> str:
    frontmatter, body = split_skill(skill_file)
    values = {
        key: field(frontmatter, key)
        for key in (
            "name", "description", "display_name", "display_name_en",
            "description_zh", "description_en", "version", "author",
        )
    }
    return "\n".join(
        [
            "---",
            f"name: {values['name']}",
            f"display_name: {values['display_name']}",
            f"display_name_en: {values['display_name_en']}",
            f"description: {values['description']}",
            f"description_zh: {values['description_zh']}",
            f"description_en: {values['description_en']}",
            f"version: {values['version']}",
            f"author: {values['author']}",
            "---",
            "",
            body,
        ]
    )


def package_files(skill_dir: Path):
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir)
        if any(part in EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield path, relative


def build(skill_dir: Path, output_dir: Path, platform: str = "standard") -> Path:
    skill_dir = skill_dir.resolve()
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"missing {skill_file}")
    version = read_version(skill_file)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = "-workbuddy" if platform == "workbuddy" else ""
    if platform not in {"standard", "workbuddy"}:
        raise ValueError(f"unsupported platform: {platform}")
    destination = output_dir / f"{skill_dir.name}{suffix}-v{version}.zip"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, relative in package_files(skill_dir):
            if platform == "workbuddy" and relative.as_posix() == "SKILL.md":
                archive.writestr("SKILL.md", workbuddy_skill(source))
            else:
                archive.write(source, relative.as_posix())
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        if "SKILL.md" not in names:
            raise RuntimeError("package is invalid: SKILL.md is not at archive root")
    return destination


def main() -> int:
    args = parse_args()
    standard = build(args.skill_dir, args.output_dir, "standard")
    workbuddy = build(args.skill_dir, args.output_dir, "workbuddy")
    print(standard)
    print(workbuddy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
