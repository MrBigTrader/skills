from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.deploy_dry_run import (
    ApplyError,
    BLOCKED,
    CREATE,
    IDENTICAL,
    LOCAL_DRIFT,
    MISSING_DEPENDENCY,
    NAME_COLLISION,
    STRUCTURAL_CONFLICT,
    UNMANAGED_CONFLICT,
    _copy_bundle_safely,
    _classify_destination,
    _promote_noreplace,
    apply_deployment,
    bundle_manifest,
    build_plan,
    destination_roots,
    destination_safety_issue,
    inventory_destination,
)


class DeployPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.destination_root = self.root / "destination"
        self.repo.mkdir()

    def make_skill(
        self,
        parent: Path,
        name: str,
        files: dict[str, str] | None = None,
        frontmatter_name: str | None = None,
    ) -> Path:
        skill = parent / name
        skill.mkdir(parents=True, exist_ok=True)
        declared_name = frontmatter_name if frontmatter_name is not None else name
        (skill / "SKILL.md").write_text(
            f"---\nname: {declared_name}\ndescription: Example.\n---\nInstructions.\n",
            encoding="utf-8",
        )
        for relative, content in (files or {}).items():
            path = skill / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return skill

    def catalog(
        self,
        name: str = "example-skill",
        targets: list[str] | None = None,
        dependencies: dict | None = None,
    ) -> dict:
        return {
            "skills": [
                {
                    "name": name,
                    "path": f"skills/{name}",
                    "targets": targets or ["codex"],
                    "dependencies": dependencies or {},
                }
            ]
        }

    def source(self, name: str = "example-skill", files: dict[str, str] | None = None) -> Path:
        return self.make_skill(self.repo / "skills", name, files)

    def single_status(self, catalog: dict, roots: dict[str, Path]) -> str:
        plan = build_plan(catalog, self.repo, roots)
        self.assertEqual(1, len(plan.operations))
        return plan.operations[0].status

    def snapshot(self, root: Path) -> str:
        digest = hashlib.sha256()
        if not root.exists():
            return digest.hexdigest()
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode())
            if path.is_file() and not path.is_symlink():
                digest.update(path.read_bytes())
        return digest.hexdigest()

    def test_create_and_ungoverned_content_remains_untouched(self) -> None:
        self.source(files={"references/guide.md": "canonical"})
        ungoverned = self.make_skill(self.destination_root, "local-only", {"marker.txt": "untouched"})
        before = self.snapshot(self.destination_root)

        plan = build_plan(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(CREATE, plan.operations[0].status)
        self.assertFalse((self.destination_root / "example-skill").exists())
        self.assertEqual("untouched", (ungoverned / "marker.txt").read_text(encoding="utf-8"))
        self.assertEqual(before, self.snapshot(self.destination_root))
        self.assertFalse(plan.blocked)

    def test_identical_compares_all_files_recursively(self) -> None:
        files = {"references/guide.md": "same", "scripts/run.py": "print('same')\n"}
        self.source(files=files)
        self.make_skill(self.destination_root, "example-skill", files)

        status = self.single_status(self.catalog(), {"codex": self.destination_root})

        self.assertEqual(IDENTICAL, status)

    def test_identical_same_name_in_another_category_is_not_a_collision(self) -> None:
        files = {"reference.md": "same"}
        self.source(files=files)
        existing = self.make_skill(self.destination_root / "category", "example-skill", files)

        plan = build_plan(self.catalog(targets=["hermes"]), self.repo, {"hermes": self.destination_root})

        self.assertEqual(IDENTICAL, plan.operations[0].status)
        self.assertIn(str(existing), plan.operations[0].detail)
        self.assertFalse(plan.blocked)

    def test_local_drift_detects_recursive_file_change(self) -> None:
        self.source(files={"references/guide.md": "canonical"})
        self.make_skill(self.destination_root, "example-skill", {"references/guide.md": "local"})

        plan = build_plan(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(LOCAL_DRIFT, plan.operations[0].status)
        self.assertTrue(plan.blocked)

    def test_unmanaged_conflict_for_existing_directory_without_valid_skill(self) -> None:
        self.source()
        destination = self.destination_root / "example-skill"
        destination.mkdir(parents=True)
        marker = destination / "marker.txt"
        marker.write_text("unmanaged", encoding="utf-8")
        before = self.snapshot(self.destination_root)

        plan = build_plan(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(UNMANAGED_CONFLICT, plan.operations[0].status)
        self.assertEqual("unmanaged", marker.read_text(encoding="utf-8"))
        self.assertEqual(before, self.snapshot(self.destination_root))

    def test_name_collision_for_different_same_name_skill_elsewhere(self) -> None:
        self.source(files={"marker.txt": "canonical"})
        self.make_skill(self.destination_root / "category", "example-skill", {"marker.txt": "different"})

        status = self.single_status(
            self.catalog(targets=["hermes"]),
            {"hermes": self.destination_root},
        )

        self.assertEqual(NAME_COLLISION, status)

    def test_structural_conflict_for_file_at_destination(self) -> None:
        self.source()
        self.destination_root.mkdir()
        (self.destination_root / "example-skill").write_text("not a directory", encoding="utf-8")

        status = self.single_status(self.catalog(), {"codex": self.destination_root})

        self.assertEqual(STRUCTURAL_CONFLICT, status)

    def test_path_escape_is_structural_conflict(self) -> None:
        source = self.source()
        configured_root = self.root / "configured"
        escaped = self.root / "outside" / "example-skill"

        issue = destination_safety_issue(configured_root, escaped)
        status, _ = _classify_destination(
            "example-skill",
            bundle_manifest(source),
            configured_root,
            escaped,
            inventory_destination(configured_root),
        )

        self.assertIsNotNone(issue)
        self.assertIn("escapes", issue or "")
        self.assertEqual(STRUCTURAL_CONFLICT, status)

    def test_symlink_or_junction_is_classified_without_following_it(self) -> None:
        self.source()
        destination = self.destination_root / "example-skill"
        destination.mkdir(parents=True)

        original = Path(os.path.abspath(destination))
        with patch(
            "scripts.deploy_dry_run._is_reparse_point",
            side_effect=lambda path: Path(os.path.abspath(path)) == original,
        ):
            status = self.single_status(self.catalog(), {"codex": self.destination_root})

        self.assertEqual(STRUCTURAL_CONFLICT, status)

    def test_missing_declared_project_file_is_missing_dependency(self) -> None:
        self.source()
        catalog = self.catalog(dependencies={"project_files": ["scripts/missing.py"]})

        status = self.single_status(catalog, {"codex": self.destination_root})

        self.assertEqual(MISSING_DEPENDENCY, status)

    def test_external_project_files_present_allow_create(self) -> None:
        self.source()
        external_root = self.root / "external-project"
        external_file = external_root / "scripts" / "run.py"
        external_file.parent.mkdir(parents=True)
        external_file.write_text("print('external')\n", encoding="utf-8")
        catalog = self.catalog(
            dependencies={
                "external_project_root": str(external_root),
                "external_project_files": ["scripts/run.py"],
            }
        )

        status = self.single_status(catalog, {"codex": self.destination_root})

        self.assertEqual(CREATE, status)

    def test_external_project_files_absent_are_missing_dependency(self) -> None:
        self.source()
        external_root = self.root / "external-project"
        catalog = self.catalog(
            dependencies={
                "external_project_root": str(external_root),
                "external_project_files": ["scripts/missing.py"],
            }
        )

        status = self.single_status(catalog, {"codex": self.destination_root})

        self.assertEqual(MISSING_DEPENDENCY, status)

    def test_external_project_files_without_resolvable_location_are_blocked(self) -> None:
        self.source()
        catalog = self.catalog(dependencies={"external_project_files": ["scripts/run.py"]})

        status = self.single_status(catalog, {"codex": self.destination_root})

        self.assertEqual(BLOCKED, status)

    def test_missing_target_root_is_blocked(self) -> None:
        self.source()

        status = self.single_status(self.catalog(), {})

        self.assertEqual(BLOCKED, status)

    def test_codex_and_gemini_shared_root_are_one_physical_operation(self) -> None:
        self.source()
        catalog = self.catalog(targets=["codex", "gemini-cli"])

        plan = build_plan(
            catalog,
            self.repo,
            {"codex": self.destination_root, "gemini-cli": self.destination_root},
        )

        self.assertEqual(1, len(plan.operations))
        self.assertEqual(("codex", "gemini-cli"), plan.operations[0].targets)
        self.assertEqual(CREATE, plan.operations[0].status)

    def test_root_resolution_is_portable_and_supports_overrides(self) -> None:
        home = self.root / "home"
        custom_codex = self.root / "custom-codex"
        roots = destination_roots(
            home=home,
            env={
                "CODEX_SKILLS_DIR": str(custom_codex),
                "HERMES_HOME": str(self.root / "hermes-home"),
            },
        )

        self.assertEqual(custom_codex, roots["codex"])
        self.assertEqual(home / ".agents" / "skills", roots["gemini-cli"])
        self.assertEqual(home / ".gemini" / "config" / "skills", roots["antigravity"])
        self.assertEqual(self.root / "hermes-home" / "skills", roots["hermes"])

    def test_relative_root_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            destination_roots(home=self.root, env={"CODEX_SKILLS_DIR": "relative/skills"})

    def test_apply_create_uses_exact_canonical_bundle(self) -> None:
        source = self.source(files={"references/guide.md": "canonical"})
        self.destination_root.mkdir()

        result = apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        destination = self.destination_root / "example-skill"
        self.assertEqual(1, len(result.created))
        self.assertEqual(0, len(result.unchanged))
        self.assertEqual(bundle_manifest(source), bundle_manifest(destination))

    def test_apply_identical_is_no_op(self) -> None:
        files = {"references/guide.md": "same"}
        self.source(files=files)
        self.make_skill(self.destination_root, "example-skill", files)
        before = self.snapshot(self.destination_root)

        result = apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(0, len(result.created))
        self.assertEqual(1, len(result.unchanged))
        self.assertEqual(before, self.snapshot(self.destination_root))

    def test_apply_blocked_preflight_produces_zero_writes(self) -> None:
        self.source(files={"marker.txt": "canonical"})
        self.make_skill(self.destination_root, "example-skill", {"marker.txt": "local"})
        before = self.snapshot(self.destination_root)

        with self.assertRaises(ApplyError) as raised:
            apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertTrue(raised.exception.plan.blocked)
        self.assertEqual((), raised.exception.completed)
        self.assertEqual(before, self.snapshot(self.destination_root))

    def test_apply_aborts_if_destination_appears_before_promotion(self) -> None:
        self.source()
        self.destination_root.mkdir()
        destination = self.destination_root / "example-skill"

        def copy_then_race(source: Path, temporary: Path) -> None:
            _copy_bundle_safely(source, temporary)
            destination.mkdir()
            (destination / "racer.txt").write_text("external", encoding="utf-8")

        with patch("scripts.deploy_dry_run._copy_bundle_safely", side_effect=copy_then_race):
            with self.assertRaisesRegex(ApplyError, "appeared before promotion"):
                apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual("external", (destination / "racer.txt").read_text(encoding="utf-8"))
        self.assertEqual([], list(self.destination_root.glob(".example-skill.deploy-*")))

    def test_apply_aborts_if_parent_becomes_reparse_before_promotion(self) -> None:
        self.source()
        self.destination_root.mkdir()
        parent = Path(os.path.abspath(self.destination_root))
        parent_changed = False

        def copy_then_change_parent(source: Path, temporary: Path) -> None:
            nonlocal parent_changed
            _copy_bundle_safely(source, temporary)
            parent_changed = True

        def simulated_reparse(path: Path) -> bool:
            return parent_changed and Path(os.path.abspath(path)) == parent

        with patch("scripts.deploy_dry_run._copy_bundle_safely", side_effect=copy_then_change_parent):
            with patch("scripts.deploy_dry_run._is_reparse_point", side_effect=simulated_reparse):
                with self.assertRaisesRegex(ApplyError, "symlink or junction"):
                    apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertFalse((self.destination_root / "example-skill").exists())
        self.assertEqual([], list(self.destination_root.glob(".example-skill.deploy-*")))

    def test_atomic_promotion_never_overwrites_existing_destination(self) -> None:
        self.destination_root.mkdir()
        temporary = self.destination_root / ".example-skill.deploy-test"
        temporary.mkdir()
        (temporary / "new.txt").write_text("new", encoding="utf-8")
        destination = self.destination_root / "example-skill"
        destination.mkdir()
        marker = destination / "existing.txt"
        marker.write_text("existing", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            _promote_noreplace(temporary, destination, self.destination_root)

        self.assertEqual("existing", marker.read_text(encoding="utf-8"))
        self.assertTrue(temporary.is_dir())

    def test_apply_symlink_or_junction_preflight_produces_zero_writes(self) -> None:
        self.source()
        self.destination_root.mkdir()
        original = Path(os.path.abspath(self.destination_root))
        before = self.snapshot(self.destination_root)

        with patch(
            "scripts.deploy_dry_run._is_reparse_point",
            side_effect=lambda path: Path(os.path.abspath(path)) == original,
        ):
            with self.assertRaises(ApplyError):
                apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(before, self.snapshot(self.destination_root))

    def test_apply_path_escape_preflight_produces_zero_writes(self) -> None:
        self.source()
        self.destination_root.mkdir()
        catalog = self.catalog(name="../escaped")
        catalog["skills"][0]["path"] = "skills/example-skill"
        before = self.snapshot(self.root)

        with self.assertRaises(ApplyError):
            apply_deployment(catalog, self.repo, {"codex": self.destination_root})

        self.assertEqual(before, self.snapshot(self.root))
        self.assertFalse((self.root / "escaped").exists())

    def test_apply_copy_failure_cleans_only_its_temporary(self) -> None:
        self.source()
        self.destination_root.mkdir()

        with patch("scripts.deploy_dry_run._copy_bundle_safely", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(ApplyError, "copy failed") as raised:
                apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual((), raised.exception.completed)
        self.assertFalse((self.destination_root / "example-skill").exists())
        self.assertEqual([], list(self.destination_root.glob(".example-skill.deploy-*")))

    def test_apply_rejects_divergent_temporary_hash(self) -> None:
        self.source()
        self.destination_root.mkdir()

        def copy_then_change(source: Path, temporary: Path) -> None:
            _copy_bundle_safely(source, temporary)
            (temporary / "SKILL.md").write_text("changed", encoding="utf-8")

        with patch("scripts.deploy_dry_run._copy_bundle_safely", side_effect=copy_then_change):
            with self.assertRaisesRegex(ApplyError, "hash mismatch"):
                apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertFalse((self.destination_root / "example-skill").exists())
        self.assertEqual([], list(self.destination_root.glob(".example-skill.deploy-*")))

    def test_apply_preserves_ungoverned_skills_absolutely(self) -> None:
        self.source(files={"canonical.txt": "canonical"})
        ungoverned = self.make_skill(
            self.destination_root / "local-category",
            "local-only",
            {"marker.txt": "untouched"},
        )
        before_manifest = bundle_manifest(ungoverned)

        apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(before_manifest, bundle_manifest(ungoverned))

    def test_apply_is_idempotent(self) -> None:
        self.source(files={"references/guide.md": "canonical"})
        self.destination_root.mkdir()

        first = apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})
        before_second = self.snapshot(self.destination_root)
        second = apply_deployment(self.catalog(), self.repo, {"codex": self.destination_root})

        self.assertEqual(1, len(first.created))
        self.assertEqual(0, len(second.created))
        self.assertEqual(1, len(second.unchanged))
        self.assertEqual(before_second, self.snapshot(self.destination_root))


if __name__ == "__main__":
    unittest.main()
