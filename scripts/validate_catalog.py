#!/usr/bin/env python
"""Validate the canonical Agent Skills catalog without changing files."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

VALID_OWNERSHIP = {"owned", "forked", "vendored", "external", "generated"}
VALID_TARGETS = {"codex", "gemini-cli", "antigravity", "hermes"}
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    catalog_count: int = 0
    filesystem_count: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"catalog not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("catalog root must be a YAML mapping")
    return data


def parse_skill_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise ValueError("SKILL.md frontmatter is not closed") from None
    try:
        metadata = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid SKILL.md YAML frontmatter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping")
    return metadata


def _inside_repo(repo_root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(repo_root)
        return True
    except ValueError:
        return False


def validate_catalog(repo_root: Path, catalog_path: Path) -> ValidationResult:
    result = ValidationResult()
    repo_root = repo_root.resolve()

    try:
        catalog = load_yaml(catalog_path)
    except (OSError, ValueError) as exc:
        result.errors.append(str(exc))
        return result

    if catalog.get("schema_version") != 1:
        result.errors.append("schema_version must be 1")

    canonical_root_value = catalog.get("canonical_root")
    if not isinstance(canonical_root_value, str) or not canonical_root_value.strip():
        result.errors.append("canonical_root must be a non-empty relative path")
        canonical_root = repo_root / "skills"
    else:
        canonical_root = (repo_root / canonical_root_value).resolve()
        if Path(canonical_root_value).is_absolute() or not _inside_repo(repo_root, canonical_root):
            result.errors.append("canonical_root must stay inside the repository")

    entries = catalog.get("skills")
    if not isinstance(entries, list):
        result.errors.append("skills must be a YAML list")
        return result
    result.catalog_count = len(entries)

    names: dict[str, int] = {}
    paths: dict[Path, str] = {}
    catalog_paths: set[Path] = set()
    related_skill_references: list[tuple[str, str]] = []

    for index, entry in enumerate(entries, start=1):
        label = f"skills[{index}]"
        if not isinstance(entry, dict):
            result.errors.append(f"{label} must be a mapping")
            continue

        name = entry.get("name")
        if not isinstance(name, str) or not name:
            result.errors.append(f"{label}.name is required")
            continue
        label = name
        if not NAME_RE.fullmatch(name) or len(name) > 64:
            result.errors.append(f"{label}: name must be <=64 lowercase letters, digits, and hyphens")
        if name in names:
            result.errors.append(f"{label}: duplicate catalog name (also entry {names[name]})")
        else:
            names[name] = index

        ownership = entry.get("ownership")
        if ownership not in VALID_OWNERSHIP:
            result.errors.append(f"{label}: invalid ownership {ownership!r}")

        targets = entry.get("targets")
        if not isinstance(targets, list) or not targets:
            result.errors.append(f"{label}: targets must be a non-empty list")
        else:
            invalid_targets = sorted(set(targets) - VALID_TARGETS)
            if invalid_targets:
                result.errors.append(f"{label}: invalid targets: {', '.join(invalid_targets)}")
            if len(targets) != len(set(targets)):
                result.errors.append(f"{label}: duplicate targets")

        source = entry.get("source")
        if not isinstance(source, dict) or not source.get("type"):
            result.errors.append(f"{label}: source.type is required")
        dependencies = entry.get("dependencies")
        if not isinstance(dependencies, dict):
            result.errors.append(f"{label}: dependencies must be a mapping")
        compatibility = entry.get("compatibility")
        if not isinstance(compatibility, dict) or not compatibility.get("status"):
            result.errors.append(f"{label}: compatibility.status is required")

        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value:
            result.errors.append(f"{label}: path is required")
            continue
        relative_path = Path(path_value)
        skill_dir = (repo_root / relative_path).resolve()
        if relative_path.is_absolute() or not _inside_repo(repo_root, skill_dir):
            result.errors.append(f"{label}: path must stay inside the repository: {path_value}")
            continue
        if canonical_root not in skill_dir.parents:
            result.errors.append(f"{label}: path is outside canonical_root: {path_value}")
        if skill_dir in paths:
            result.errors.append(f"{label}: path collision with {paths[skill_dir]}: {path_value}")
        else:
            paths[skill_dir] = name
        catalog_paths.add(skill_dir)

        if not skill_dir.is_dir():
            result.errors.append(f"{label}: catalog path does not exist: {path_value}")
            continue
        if skill_dir.name != name:
            result.errors.append(f"{label}: folder {skill_dir.name!r} must equal frontmatter/catalog name")

        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            result.errors.append(f"{label}: missing SKILL.md")
            continue
        try:
            metadata = parse_skill_frontmatter(skill_md)
        except (OSError, UnicodeError, ValueError) as exc:
            result.errors.append(f"{label}: {exc}")
            continue
        skill_name = metadata.get("name")
        description = metadata.get("description")
        if skill_name != name:
            result.errors.append(f"{label}: SKILL.md name {skill_name!r} does not match catalog name")
        if not isinstance(description, str) or not description.strip():
            result.errors.append(f"{label}: SKILL.md description is required")

        if isinstance(dependencies, dict):
            for key in ("bundled_scripts", "bundled_resources", "optional_files"):
                references = dependencies.get(key, [])
                if not isinstance(references, list):
                    result.errors.append(f"{label}: dependencies.{key} must be a list")
                    continue
                for reference in references:
                    if not isinstance(reference, str) or not reference:
                        result.errors.append(f"{label}: dependencies.{key} contains an invalid reference")
                        continue
                    referenced_path = (skill_dir / reference).resolve()
                    if not _inside_repo(skill_dir, referenced_path) or not referenced_path.exists():
                        result.errors.append(f"{label}: broken bundled reference: {reference}")
            related = dependencies.get("related_skills", [])
            if not isinstance(related, list):
                result.errors.append(f"{label}: dependencies.related_skills must be a list")
            else:
                related_skill_references.extend((label, reference) for reference in related if isinstance(reference, str))

    filesystem_paths: set[Path] = set()
    filesystem_names: dict[str, Path] = {}
    if canonical_root.is_dir():
        for skill_md in sorted(canonical_root.glob("*/SKILL.md")):
            skill_dir = skill_md.parent.resolve()
            filesystem_paths.add(skill_dir)
            try:
                metadata = parse_skill_frontmatter(skill_md)
                skill_name = metadata.get("name")
            except (OSError, UnicodeError, ValueError) as exc:
                result.errors.append(f"{skill_md.relative_to(repo_root)}: {exc}")
                continue
            if isinstance(skill_name, str):
                previous = filesystem_names.get(skill_name)
                if previous and previous != skill_dir:
                    result.errors.append(
                        f"filesystem name collision {skill_name!r}: "
                        f"{previous.relative_to(repo_root)} and {skill_dir.relative_to(repo_root)}"
                    )
                filesystem_names[skill_name] = skill_dir
    result.filesystem_count = len(filesystem_paths)

    for uncataloged in sorted(filesystem_paths - catalog_paths):
        result.errors.append(f"uncataloged skill directory: {uncataloged.relative_to(repo_root)}")
    for missing in sorted(catalog_paths - filesystem_paths):
        result.errors.append(f"catalog references a non-skill directory: {missing.relative_to(repo_root)}")
    for owner, reference in related_skill_references:
        if reference not in names:
            result.errors.append(f"{owner}: broken related skill reference: {reference}")

    return result


def format_result(result: ValidationResult) -> str:
    lines = [
        f"Catalog entries: {result.catalog_count}",
        f"Filesystem skills: {result.filesystem_count}",
        f"Errors: {len(result.errors)}",
        f"Warnings: {len(result.warnings)}",
    ]
    lines.extend(f"ERROR: {message}" for message in result.errors)
    lines.extend(f"WARNING: {message}" for message in result.warnings)
    lines.append("VALID" if result.ok else "INVALID")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    catalog_path = args.catalog.resolve() if args.catalog else repo_root / "catalog.yaml"
    result = validate_catalog(repo_root, catalog_path)
    print(format_result(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
