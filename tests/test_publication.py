import json
import tempfile
import unittest
from pathlib import Path

from tools.publication_audit import check_tree, content_findings


class PublicationTests(unittest.TestCase):
    def tree(self, directory):
        root = Path(directory)
        manifest = {"files": [{"path": "public-allowlist.json"}, {"path": "README.md"}]}
        (root / "public-allowlist.json").write_text(json.dumps(manifest) + "\n")
        (root / "README.md").write_text("# Synthetic test tree\n")
        return root

    def test_complete_allowlisted_tree_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(check_tree(self.tree(directory)), [])

    def test_unexpected_file_is_rejected_even_if_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.tree(directory)
            (root / "unexpected.txt").write_text("synthetic\n")
            self.assertTrue(any(item.startswith("unexpected:") for item in check_tree(root)))

    def test_git_metadata_and_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.tree(directory)
            (root / ".git").mkdir()
            self.assertIn("git-metadata-in-candidate", check_tree(root))
            (root / "link").symlink_to(root / "README.md")
            self.assertTrue(any(item.startswith("symlink:") for item in check_tree(root)))

    def test_private_context_is_rejected_without_a_token(self):
        for value in ["/srv" + "/application/location", "proj_" + "Z" * 20,
                      "https://" + "private-system.example.net/path", "person@" + "sample.net"]:
            with self.subTest(kind=value[:3]):
                self.assertTrue(content_findings(value, "README.md"))

    def test_private_address_only_allowed_as_reviewed_test_fixture(self):
        address = "10." + "0.0.1"
        self.assertIn("private-address", content_findings(address, "README.md"))
        self.assertEqual(content_findings(address, "tests/test_contracts.py"), [])

    def test_loopback_only_allowed_in_the_reviewed_homolog_harness(self):
        address = "127." + "0.0.1"
        self.assertEqual(content_findings(address, "careerbrain/homolog.py"), [])
        self.assertIn("private-address", content_findings(address, "docs/homolog-10.md"))
        wildcard = "0." + "0.0.0"
        self.assertEqual(content_findings(wildcard, "tests/integration/homolog_cases.py"), [])
        self.assertIn("private-address", content_findings(wildcard, "careerbrain/homolog.py"))

    def test_operational_host_rejected_in_docs(self):
        self.assertEqual(content_findings("https://api.example.org/v1", "README.md"), [])
        self.assertIn("unapproved-url-host", content_findings("https://" + "runtime.example.net/v1", "README.md"))

    def test_missing_and_traversal_entries_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.tree(directory)
            (root / "README.md").unlink()
            self.assertIn("missing:README.md", check_tree(root))
            (root / "public-allowlist.json").write_text(json.dumps({"files": [{"path": "../outside"}]}) + "\n")
            self.assertIn("unsafe-allowlist-path", check_tree(root))
