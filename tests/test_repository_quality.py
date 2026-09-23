import re
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> tuple[dict, str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    # BaseLoader intentionally keeps GitHub's `on` key as a string instead of
    # applying YAML 1.1's obsolete boolean interpretation.
    document = yaml.load(text, Loader=yaml.BaseLoader)
    if not isinstance(document, dict):
        raise AssertionError(f"{name} must contain a YAML mapping")
    return document, text


class RepositoryAutomationTests(unittest.TestCase):
    def test_ci_is_a_least_privilege_push_and_pull_request_gate(self):
        workflow, text = _workflow("ci.yml")

        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["on"]), {"push", "pull_request"})
        self.assertIn("requirements-test.txt", text)
        self.assertIn("requirements-build.txt", text)
        install_step = next(
            step
            for step in workflow["jobs"]["non-browser-tests"]["steps"]
            if step.get("name")
            == "Install locked runtime, test, and release-tooling dependencies"
        )
        self.assertEqual(
            install_step["run"],
            "python -m pip install -r requirements-test.txt "
            "-r requirements-build.txt",
        )
        self.assertIn("python -m pip check", text)
        self.assertIn('-m "not browser"', text)
        self.assertIn("git diff --check", text)
        self.assertIn("tests/test_release_package_verification.py", text)
        self.assertIn("git status --porcelain --untracked-files=all", text)
        self.assertNotRegex(text, re.compile(r"(?im)^\s*run:.*pyinstaller"))

    def test_firefox_gate_is_scheduled_and_manual_not_a_pull_request_gate(self):
        workflow, text = _workflow("firefox.yml")

        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch", "schedule"})
        self.assertIn("firefox --version", text)
        self.assertIn("DLMS_RUN_BROWSER_TESTS", text)
        self.assertIn("tests/browser/test_critical_workflows.py", text)
        self.assertNotIn("pull_request", workflow["on"])
        self.assertNotIn("push", workflow["on"])

    def test_firefox_gate_explicitly_owns_virtual_display_without_masking_failures(self):
        workflow, text = _workflow("firefox.yml")
        job = workflow["jobs"]["firefox-workflows"]
        self.assertEqual(job["runs-on"], "ubuntu-24.04")
        gate = job["steps"][-1]
        self.assertEqual(gate["env"]["DLMS_FIREFOX_MODE"], "xvfb")
        self.assertEqual(gate["env"]["DLMS_RUN_BROWSER_TESTS"], "1")
        self.assertIn('xvfb-run --auto-servernum', gate["run"])
        self.assertIn('-screen 0 1920x1080x24 -nolisten tcp', gate["run"])
        self.assertIn("bash -euc", gate["run"])
        self.assertNotIn("|| true", gate["run"])
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn("MOZ_WEBRENDER=0", text)
        self.assertIn('sudo apt-get install --no-install-recommends -y xvfb xauth', text)

    def test_dependency_audit_is_bounded_scheduled_and_manual(self):
        workflow, text = _workflow("dependency-audit.yml")

        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(workflow["on"]), {"workflow_dispatch", "schedule"})
        self.assertIn("python -m pip install -r requirements-audit.txt", text)
        self.assertIn("--requirement requirements-build.txt", text)
        self.assertIn("--requirement requirements-test.txt", text)
        self.assertNotIn("continue-on-error", text)

        audit_requirements = (ROOT / "requirements-audit.txt").read_text(
            encoding="utf-8"
        )
        self.assertRegex(audit_requirements, r"(?m)^pip-audit==\d+\.\d+\.\d+$")

    def test_dependabot_covers_python_and_workflow_dependencies(self):
        document = yaml.safe_load(
            (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
        )
        ecosystems = {
            update["package-ecosystem"]: update for update in document["updates"]
        }

        self.assertEqual(set(ecosystems), {"pip", "github-actions"})
        for update in ecosystems.values():
            self.assertEqual(update["directory"], "/")
            self.assertEqual(update["schedule"]["interval"], "weekly")


class RepositoryGuidanceTests(unittest.TestCase):
    def test_security_policy_states_the_actual_trust_boundaries(self):
        policy = (ROOT / "SECURITY.md").read_text(encoding="utf-8")

        for phrase in (
            "private vulnerability-reporting",
            "loopback interface",
            "trusted,\nappropriately firewalled network",
            "authentication, authorization, or TLS",
            "public internet",
            "synthetic data",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, policy)

    def test_contributor_guide_covers_tests_privacy_and_high_impact_changes(self):
        guide = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

        for phrase in (
            "requirements-test.txt",
            '-m "not browser"',
            "git diff --check",
            "DLMS_RUN_BROWSER_TESTS",
            "neutral, self-created synthetic fixtures",
            "Never commit real personal data",
            "schemas, migrations, persistence",
            "release verification",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, guide)


if __name__ == "__main__":
    unittest.main()
