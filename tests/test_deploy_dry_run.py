from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.deploy_dry_run import build_plan, render_plan


class DeployDryRunTests(unittest.TestCase):
    def test_plan_is_descriptive_and_does_not_create_destinations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            roots = {
                "codex": root / "codex",
                "gemini-cli": root / "gemini",
                "antigravity": root / "antigravity",
                "hermes": root / "hermes",
            }
            catalog = {
                "skills": [
                    {
                        "name": "example-skill",
                        "targets": ["codex", "gemini-cli", "antigravity", "hermes"],
                    }
                ]
            }

            plan = build_plan(catalog, roots)
            output = render_plan(plan)

            self.assertEqual(4, len(plan))
            self.assertIn("executed operations: 0", output)
            self.assertIn("would create", output)
            self.assertTrue(all(not path.exists() for path in roots.values()))

    def test_existing_destination_is_only_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            destination_root = root / "codex"
            destination = destination_root / "example-skill"
            destination.mkdir(parents=True)
            marker = destination / "marker.txt"
            marker.write_text("untouched", encoding="utf-8")

            plan = build_plan(
                {"skills": [{"name": "example-skill", "targets": ["codex"]}]},
                {"codex": destination_root},
            )

            self.assertEqual("would review/update", plan[0][3])
            self.assertEqual("untouched", marker.read_text(encoding="utf-8"))

    def test_name_collision_outside_destination_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "hermes" / "software-development" / "example-skill"
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text(
                "---\nname: example-skill\ndescription: Existing.\n---\n",
                encoding="utf-8",
            )

            plan = build_plan(
                {"skills": [{"name": "example-skill", "targets": ["hermes"]}]},
                {"hermes": root / "hermes"},
            )

            self.assertIn("blocked: name collision", plan[0][3])
            self.assertTrue((existing / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
