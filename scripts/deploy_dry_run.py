#!/usr/bin/env python
"""Print a conceptual, read-only deployment plan for cataloged skills."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from .validate_catalog import load_yaml, parse_skill_frontmatter, validate_catalog
except ImportError:  # Direct execution: python scripts/deploy_dry_run.py
    from validate_catalog import load_yaml, parse_skill_frontmatter, validate_catalog


def destination_roots(home: Path | None = None, hermes_home: Path | None = None) -> dict[str, Path]:
    home = (home or Path.home()).resolve()
    if hermes_home is None:
        configured = os.environ.get("HERMES_HOME")
        hermes_home = Path(configured) if configured else home / ".hermes"
    return {
        "codex": home / ".agents" / "skills",
        "gemini-cli": home / ".agents" / "skills",
        "antigravity": home / ".gemini" / "config" / "skills",
        "hermes": hermes_home.resolve() / "skills",
    }


def discovered_skill_paths(root: Path) -> dict[str, list[Path]]:
    discovered: dict[str, list[Path]] = {}
    if not root.is_dir():
        return discovered
    for skill_md in root.rglob("SKILL.md"):
        try:
            name = parse_skill_frontmatter(skill_md).get("name")
        except (OSError, UnicodeError, ValueError):
            continue
        if isinstance(name, str):
            discovered.setdefault(name, []).append(skill_md.parent.resolve())
    return discovered


def proposed_action(name: str, destination: Path, existing: dict[str, list[Path]]) -> str:
    destination = destination.resolve()
    collisions = [path for path in existing.get(name, []) if path != destination]
    if collisions:
        locations = ", ".join(str(path) for path in sorted(collisions))
        return f"blocked: name collision at {locations}"
    return "would review/update" if destination.exists() else "would create"


def destination_for(target: str, root: Path, name: str) -> Path:
    return root / "canonical" / name if target == "hermes" else root / name


def build_plan(catalog: dict, roots: dict[str, Path]) -> list[tuple[str, str, Path, str]]:
    plan: list[tuple[str, str, Path, str]] = []
    existing_by_target = {target: discovered_skill_paths(root) for target, root in roots.items()}
    for skill in sorted(catalog["skills"], key=lambda item: item["name"]):
        for target in skill["targets"]:
            destination = destination_for(target, roots[target], skill["name"])
            action = proposed_action(skill["name"], destination, existing_by_target[target])
            plan.append((skill["name"], target, destination, action))
    return plan


def render_plan(plan: list[tuple[str, str, Path, str]]) -> str:
    lines = [
        "DRY RUN ONLY — no files will be copied, deleted, overwritten, linked, or created.",
        "skill | platform | destination | proposed action",
        "--- | --- | --- | ---",
    ]
    lines.extend(f"{skill} | {platform} | {destination} | {action}" for skill, platform, destination, action in plan)
    lines.append(f"Planned operations: {len(plan)}; executed operations: 0")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    catalog_path = args.catalog.resolve() if args.catalog else repo_root / "catalog.yaml"

    validation = validate_catalog(repo_root, catalog_path)
    if not validation.ok:
        for error in validation.errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    catalog = load_yaml(catalog_path)
    print(render_plan(build_plan(catalog, destination_roots())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
