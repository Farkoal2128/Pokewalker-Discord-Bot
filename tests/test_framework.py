import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class FrameworkTests(unittest.TestCase):
    def test_project_identity_preserves_template_provenance(self):
        meta = json.loads((ROOT / ".template.json").read_text())
        self.assertEqual(meta["mode"], "project")
        self.assertEqual(meta["repository"], "Farkoal2128/Pokewalker-Discord-Bot")
        self.assertEqual(meta["canonical_repository"], "Farkoal2128/template-repo")
        self.assertEqual(meta["policy"], "copy-only")

    def test_contract_and_tdd_skills_exist(self):
        for path in [
            ".agents/skills/tdd/SKILL.md",
            ".agents/skills/contract-change/SKILL.md",
            ".agents/skills/implement-feature/SKILL.md",
            ".agents/skills/drive-feature/SKILL.md",
        ]:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_multi_agent_team_contract_exists(self):
        for path in [
            ".agents/skills/multi-agent-orchestration/SKILL.md",
            ".agents/team/README.md",
            ".agents/team/roles/lead-developer.md",
            ".agents/team/roles/developer-a.md",
            ".agents/team/roles/developer-b.md",
            ".agents/team/roles/testing-agent.md",
            ".agents/team/roles/documentation-agent.md",
            "docs/multi-agent-workflow.md",
            "docs/templates/agent-work-order.md",
            ".codex/config.toml",
            ".codex/agents/developer-a.toml",
            ".codex/agents/developer-b.toml",
            ".codex/agents/tester.toml",
            ".codex/agents/documentation.toml",
        ]:
            self.assertTrue((ROOT / path).is_file(), path)

    def test_codex_default_team_is_root_lead_plus_four_subagents(self):
        with (ROOT / ".codex/config.toml").open("rb") as handle:
            config = tomllib.load(handle)
        agents = config["agents"]
        self.assertTrue(agents["enabled"])
        self.assertEqual(agents["max_concurrent_threads_per_session"], 4)
        for role in ["developer_a", "developer_b", "tester", "documentation"]:
            self.assertIn(role, agents)
        self.assertNotIn("lead_developer", agents)

    def test_developer_agents_use_requested_model(self):
        for role in ["developer-a", "developer-b"]:
            with self.subTest(role=role):
                with (ROOT / f".codex/agents/{role}.toml").open("rb") as handle:
                    config = tomllib.load(handle)
                self.assertEqual(config["model"], "gpt-6.1-sol")

    def test_application_checks_active_with_unit_and_contract(self):
        commands = json.loads((ROOT / ".project/commands.json").read_text())
        self.assertEqual(commands["stage"], "active")
        for name in ("unit", "contract"):
            self.assertIsInstance(commands["checks"][name], str)
            self.assertTrue(commands["checks"][name].strip())

if __name__ == "__main__":
    unittest.main()
