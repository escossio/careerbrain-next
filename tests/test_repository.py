import json
import re
import unittest

import yaml

from tools.contracts import ROOT, SCHEMAS
from tools.repository_policy import violations


class RepositoryTests(unittest.TestCase):
    def test_secret_detector_rejects_known_credential_forms(self):
        candidates = ["sk-" + "proj-" + "A" * 40, "ghp_" + "B" * 30,
                      "GOCSPX-" + "C" * 25, "AIza" + "D" * 32,
                      "-----BEGIN " + "PRIVATE KEY-----"]
        for text in candidates:
            with self.subTest(prefix=text[:3]):
                self.assertTrue(violations(text))
        self.assertFalse(violations("synthetic-not-a-session"))

    def test_workflows_have_pins_timeouts_and_no_secret_or_deploy(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            text = path.read_text()
            value = yaml.safe_load(text)
            self.assertEqual(value["permissions"], {"contents": "read"})
            self.assertNotIn("pull_request_target", text)
            self.assertNotIn("secrets.", text)
            self.assertNotIn("docker ", text)
            for job in value["jobs"].values():
                self.assertLessEqual(job["timeout-minutes"], 5)
                self.assertNotIn("services", job)
                for step in job["steps"]:
                    if "uses" in step:
                        self.assertRegex(step["uses"], r"^[\w/-]+@[a-f0-9]{40}$")
                        if step["uses"].startswith("actions/checkout@"):
                            self.assertIs(step["with"]["persist-credentials"], False)

    def test_worker_probe_requires_separate_authorization(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/worker-readiness.yml").read_text())
        self.assertEqual(workflow["jobs"]["probe"]["needs"], "authorization")
        self.assertIn("careerbrain-next", workflow["jobs"]["probe"]["runs-on"])
        self.assertIn("NEXT_WORKERS_APPROVED", workflow["jobs"]["authorization"]["steps"][0]["env"]["APPROVED"])

    def test_exactly_ten_execution_sections_and_no_09_mobile_acceptance(self):
        plan = (ROOT / "PLANO_DE_EXECUCAO.md").read_text()
        self.assertEqual(re.findall(r"^### Execução (\d\d)/10", plan, re.M),
                         [f"{n:02}" for n in range(1, 11)])
        ninth = plan.split("### Execução 09/10")[1].split("### Execução 10/10")[0]
        self.assertIn("aceite da 10", ninth)
        self.assertIn("02–05", plan.split("### Execução 06/10")[1].split("### Execução 07/10")[0])

    def test_openapi_refs_resolve_and_all_private_routes_require_auth(self):
        api = json.loads((ROOT / "contracts/openapi.json").read_text())
        self.assertEqual(api["openapi"], "3.1.0")
        operations = set()
        def walk(value):
            if isinstance(value, dict):
                if "$ref" in value:
                    ref = value["$ref"]
                    if ref.startswith("#/components/schemas/"):
                        self.assertIn(ref.rsplit("/", 1)[1], api["components"]["schemas"])
                    else:
                        self.assertTrue((ROOT / "contracts" / ref).is_file())
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(api)
        for path, methods in api["paths"].items():
            for operation in methods.values():
                self.assertNotIn(operation["operationId"], operations)
                operations.add(operation["operationId"])
                if path not in {"/v1/auth/challenges", "/v1/auth/google", "/v1/auth/refresh"}:
                    self.assertTrue(operation["security"])
        self.assertEqual(set(api["components"]["schemas"]), set(SCHEMAS))

    def test_public_allowlist_is_explicit(self):
        manifest = json.loads((ROOT / "public-allowlist.json").read_text())
        paths = [entry["path"] for entry in manifest["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertIn("public-allowlist.json", paths)
        for path in paths:
            self.assertNotIn("..", path.split("/"))
            self.assertFalse(path.startswith("/"))
            self.assertTrue((ROOT / path).is_file())
