from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.validate_catalog import validate_catalog


class ValidateCatalogTests(unittest.TestCase):
    def make_repo(self) -> tuple[tempfile.TemporaryDirectory, Path, dict]:
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        skill_dir = root / "skills" / "example-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: example-skill\ndescription: Example.\n---\nInstructions.\n",
            encoding="utf-8",
        )
        catalog = {
            "schema_version": 1,
            "canonical_root": "skills",
            "skills": [
                {
                    "name": "example-skill",
                    "path": "skills/example-skill",
                    "ownership": "owned",
                    "targets": ["codex", "hermes"],
                    "source": {"type": "repository"},
                    "dependencies": {},
                    "compatibility": {"status": "portable"},
                }
            ],
        }
        return temp, root, catalog

    def write_catalog(self, root: Path, catalog: dict) -> Path:
        path = root / "catalog.yaml"
        path.write_text(yaml.safe_dump(catalog, sort_keys=False), encoding="utf-8")
        return path

    def test_valid_catalog(self) -> None:
        temp, root, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        result = validate_catalog(root, self.write_catalog(root, catalog))
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(1, result.catalog_count)
        self.assertEqual(1, result.filesystem_count)

    def test_detects_folder_name_mismatch(self) -> None:
        temp, root, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        catalog["skills"][0]["name"] = "different-name"
        result = validate_catalog(root, self.write_catalog(root, catalog))
        self.assertFalse(result.ok)
        self.assertTrue(any("must equal" in error for error in result.errors))

    def test_detects_duplicates_invalid_targets_and_path_collisions(self) -> None:
        temp, root, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        duplicate = dict(catalog["skills"][0])
        duplicate["targets"] = ["codex", "invalid-target"]
        catalog["skills"].append(duplicate)
        result = validate_catalog(root, self.write_catalog(root, catalog))
        self.assertFalse(result.ok)
        self.assertTrue(any("duplicate catalog name" in error for error in result.errors))
        self.assertTrue(any("invalid targets" in error for error in result.errors))
        self.assertTrue(any("path collision" in error for error in result.errors))

    def test_detects_uncataloged_and_missing_skill_directories(self) -> None:
        temp, root, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        extra = root / "skills" / "extra-skill"
        extra.mkdir()
        (extra / "SKILL.md").write_text(
            "---\nname: extra-skill\ndescription: Extra.\n---\n",
            encoding="utf-8",
        )
        catalog["skills"][0]["path"] = "skills/missing-skill"
        result = validate_catalog(root, self.write_catalog(root, catalog))
        self.assertFalse(result.ok)
        self.assertTrue(any("does not exist" in error for error in result.errors))
        self.assertTrue(any("uncataloged skill directory" in error for error in result.errors))
        self.assertTrue(any("non-skill directory" in error for error in result.errors))

    def test_detects_broken_catalog_references(self) -> None:
        temp, root, catalog = self.make_repo()
        self.addCleanup(temp.cleanup)
        catalog["skills"][0]["dependencies"] = {
            "bundled_scripts": ["scripts/missing.py"],
            "related_skills": ["missing-skill"],
        }
        result = validate_catalog(root, self.write_catalog(root, catalog))
        self.assertFalse(result.ok)
        self.assertTrue(any("broken bundled reference" in error for error in result.errors))
        self.assertTrue(any("broken related skill reference" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
