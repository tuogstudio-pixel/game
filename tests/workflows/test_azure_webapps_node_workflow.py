"""Tests for the .github/workflows/azure-webapps-node.yml GitHub Actions workflow.

This workflow builds a Node.js application and deploys it to an Azure Web
App. The tests below validate:

  * That the file is syntactically valid YAML (a hard requirement for any
    GitHub Actions workflow file - GitHub will refuse to run a workflow
    that fails to parse).
  * The overall structure of the workflow (triggers, env vars, permissions,
    jobs, steps and the actions/versions used within them).
  * A handful of regression checks that guard against a real defect
    observed in this file: unrelated `action.yml` documentation snippets
    (for `actions/setup-node` and `actions/setup-dotnet`) were accidentally
    appended after the last valid step, which both breaks YAML parsing and
    introduces an unrelated .NET setup step into a Node.js-only workflow.

No third-party test runner is required: everything here relies on
``unittest`` and ``yaml`` (PyYAML), which are available in this
environment. The suite can be run with:

    python3 -m unittest tests.workflows.test_azure_webapps_node_workflow -v
"""
import pathlib
import re
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "azure-webapps-node.yml"


class WorkflowFileExistsTest(unittest.TestCase):
    def test_workflow_file_exists(self):
        self.assertTrue(
            WORKFLOW_PATH.is_file(),
            f"Expected workflow file at {WORKFLOW_PATH}",
        )

    def test_workflow_file_is_not_empty(self):
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertTrue(content.strip(), "Workflow file should not be empty")


class WorkflowYamlValidityTest(unittest.TestCase):
    """The workflow file must be parseable as a single YAML document.

    GitHub Actions will not run a workflow file that fails to parse, so
    this is a hard functional requirement, not merely a style concern.
    """

    def test_workflow_file_is_valid_yaml(self):
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            self.fail(
                "azure-webapps-node.yml is not valid YAML and will be "
                f"rejected by GitHub Actions: {exc}"
            )

    def test_workflow_file_top_level_is_a_mapping(self):
        # A GitHub Actions workflow document's top level must be a mapping
        # (keys like `on`, `env`, `jobs`, ...), never a sequence. Loading
        # is wrapped so this test reports a clear failure instead of an
        # unhandled parser error if the file is malformed.
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            self.fail(f"Could not parse workflow YAML: {exc}")
        self.assertIsInstance(
            data, dict, "Top level of the workflow document must be a mapping"
        )


class WorkflowRawContentRegressionTest(unittest.TestCase):
    """Text-level regression checks that do not depend on successful parsing.

    These target the specific defect where `action.yml` input documentation
    for `actions/setup-node` and `actions/setup-dotnet` was pasted into the
    workflow file after the real `deploy` job, at column 0.
    """

    @classmethod
    def setUpClass(cls):
        cls.content = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.lines = cls.content.splitlines()

    def test_no_unindented_list_items_after_header(self):
        # A well-formed workflow's top level is a mapping, so no line
        # should start a YAML sequence item at column 0.
        offending = [
            (i + 1, line)
            for i, line in enumerate(self.lines)
            if re.match(r"^-\s", line)
        ]
        self.assertEqual(
            offending,
            [],
            "Found unindented top-level list item(s), indicating leaked "
            f"content was appended to the workflow: {offending}",
        )

    def test_no_leaked_setup_dotnet_action(self):
        self.assertNotIn(
            "actions/setup-dotnet",
            self.content,
            "This is a Node.js-only workflow; it should not reference "
            "actions/setup-dotnet",
        )
        self.assertNotIn("Setup .NET Core SDK", self.content)

    def test_no_duplicate_setup_node_action_reference(self):
        occurrences = self.content.count("actions/setup-node")
        self.assertEqual(
            occurrences,
            1,
            "Expected exactly one actions/setup-node reference, found "
            f"{occurrences} (possible leaked/duplicated action metadata)",
        )

    def test_no_leaked_action_metadata_placeholder_comments(self):
        # Genuine action.yml documentation uses "# optional" placeholders
        # for undocumented input values; these should never appear in an
        # actual workflow file.
        self.assertNotIn(
            "# optional",
            self.content,
            "Found leftover action.yml input documentation in the "
            "workflow file",
        )


class WorkflowStructureTest(unittest.TestCase):
    """Structural checks against the parsed workflow document.

    If the document fails to parse, these are skipped (the dedicated
    ``WorkflowYamlValidityTest`` above is responsible for reporting the
    parse failure); there is no useful structure to assert on an
    unparsable file.
    """

    @classmethod
    def setUpClass(cls):
        content = WORKFLOW_PATH.read_text(encoding="utf-8")
        try:
            cls.workflow = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            raise unittest.SkipTest(
                f"Workflow YAML does not parse, skipping structural checks: {exc}"
            )

    def test_top_level_keys_present(self):
        for key in ("on", "env", "permissions", "jobs"):
            self.assertIn(key, self.workflow)

    def test_triggers(self):
        # PyYAML parses the bare `on:` key as boolean True.
        triggers = self.workflow.get("on", self.workflow.get(True))
        self.assertIn("push", triggers)
        self.assertEqual(triggers["push"].get("branches"), ["main"])
        self.assertIn("workflow_dispatch", triggers)

    def test_env_vars(self):
        env = self.workflow["env"]
        self.assertEqual(env.get("AZURE_WEBAPP_NAME"), "your-app-name")
        self.assertEqual(env.get("AZURE_WEBAPP_PACKAGE_PATH"), ".")
        self.assertEqual(env.get("NODE_VERSION"), "20.x")

    def test_top_level_permissions(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})

    def test_jobs_present(self):
        jobs = self.workflow["jobs"]
        self.assertIn("build", jobs)
        self.assertIn("deploy", jobs)

    def test_build_job_runs_on_ubuntu(self):
        build = self.workflow["jobs"]["build"]
        self.assertEqual(build["runs-on"], "ubuntu-latest")

    def test_build_job_step_actions_in_order(self):
        steps = self.workflow["jobs"]["build"]["steps"]
        used_actions = [s.get("uses") for s in steps if "uses" in s]
        self.assertEqual(
            used_actions,
            [
                "actions/checkout@v4",
                "actions/setup-node@v4",
                "actions/upload-artifact@v4",
            ],
        )

    def test_build_job_setup_node_uses_env_version(self):
        steps = self.workflow["jobs"]["build"]["steps"]
        setup_node = next(s for s in steps if s.get("uses") == "actions/setup-node@v4")
        self.assertEqual(setup_node["with"]["node-version"], "${{ env.NODE_VERSION }}")
        self.assertEqual(setup_node["with"]["cache"], "npm")

    def test_build_job_install_build_test_step(self):
        steps = self.workflow["jobs"]["build"]["steps"]
        run_step = next(s for s in steps if "run" in s)
        self.assertIn("npm install", run_step["run"])
        self.assertIn("npm run build --if-present", run_step["run"])
        self.assertIn("npm run test --if-present", run_step["run"])

    def test_build_job_upload_artifact_step(self):
        steps = self.workflow["jobs"]["build"]["steps"]
        upload_step = next(
            s for s in steps if s.get("uses") == "actions/upload-artifact@v4"
        )
        self.assertEqual(upload_step["with"]["name"], "node-app")
        self.assertEqual(upload_step["with"]["path"], ".")

    def test_deploy_job_depends_on_build(self):
        deploy = self.workflow["jobs"]["deploy"]
        self.assertEqual(deploy["needs"], "build")

    def test_deploy_job_permissions_contents_none(self):
        deploy = self.workflow["jobs"]["deploy"]
        self.assertEqual(deploy["permissions"], {"contents": "none"})

    def test_deploy_job_environment(self):
        deploy = self.workflow["jobs"]["deploy"]
        self.assertEqual(deploy["environment"]["name"], "Development")
        self.assertEqual(
            deploy["environment"]["url"],
            "${{ steps.deploy-to-webapp.outputs.webapp-url }}",
        )

    def test_deploy_job_step_actions_in_order(self):
        steps = self.workflow["jobs"]["deploy"]["steps"]
        used_actions = [s.get("uses") for s in steps if "uses" in s]
        self.assertEqual(
            used_actions,
            ["actions/download-artifact@v4", "azure/webapps-deploy@v2"],
        )

    def test_deploy_job_download_artifact_step(self):
        steps = self.workflow["jobs"]["deploy"]["steps"]
        download_step = next(
            s for s in steps if s.get("uses") == "actions/download-artifact@v4"
        )
        self.assertEqual(download_step["with"]["name"], "node-app")

    def test_deploy_job_azure_webapps_deploy_step(self):
        steps = self.workflow["jobs"]["deploy"]["steps"]
        deploy_step = next(
            s for s in steps if s.get("uses") == "azure/webapps-deploy@v2"
        )
        self.assertEqual(deploy_step.get("id"), "deploy-to-webapp")
        self.assertEqual(
            deploy_step["with"]["app-name"], "${{ env.AZURE_WEBAPP_NAME }}"
        )
        self.assertEqual(
            deploy_step["with"]["publish-profile"],
            "${{ secrets.AZURE_WEBAPP_PUBLISH_PROFILE }}",
        )
        self.assertEqual(
            deploy_step["with"]["package"],
            "${{ env.AZURE_WEBAPP_PACKAGE_PATH }}",
        )

    def test_no_dotnet_related_steps(self):
        # This is a Node.js-only deployment workflow; asserting there is no
        # dotnet setup job/step guards against unrelated content leaking in.
        for job in self.workflow["jobs"].values():
            for step in job.get("steps", []):
                self.assertNotIn("dotnet", str(step.get("uses", "")).lower())


if __name__ == "__main__":
    unittest.main()