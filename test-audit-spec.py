"""Regression tests for the replacement audit itself, not the product runtime."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("societas_audit", ROOT / "audit-spec.py")
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class AuditTests(unittest.TestCase):
    def run_fixture(self, before: str = "", after: str = "", filename: str = "10-contracts-mvp-roadmap.md") -> dict:
        with tempfile.TemporaryDirectory(prefix="societas-audit-test-") as directory:
            root = Path(directory)
            for path in ROOT.glob("*.md"):
                text = path.read_text(encoding="utf-8")
                if before and path.name == filename:
                    self.assertIn(before, text)
                    text = text.replace(before, after, 1)
                (root / path.name).write_text(text, encoding="utf-8")
            return AUDIT.audit(root, None)

    def assert_failed(self, report: dict, prefix: str) -> None:
        self.assertFalse(report["passed"])
        self.assertTrue(any(
            not check["passed"] and check["name"].startswith(prefix)
            for check in report["checks"]
        ), prefix)

    def test_current_contracts_pass(self) -> None:
        self.assertTrue(self.run_fixture()["passed"])

    def test_missing_pause_schema_is_detected(self) -> None:
        report = self.run_fixture(
            '"$id": "urn:societas:1:task_paused"',
            '"$id": "urn:societas:1:missing_pause"',
        )
        self.assert_failed(report, "registry:task.paused")

    def test_duplicate_schema_id_is_detected(self) -> None:
        report = self.run_fixture(
            '"$id": "urn:societas:1:task_paused"',
            '"$id": "urn:societas:1:task_resumed"',
        )
        self.assert_failed(report, "unique_schema_id:")

    def test_dangling_ref_is_detected(self) -> None:
        report = self.run_fixture(
            '"$ref": "urn:societas:1:common#/$defs/evt_id"',
            '"$ref": "urn:societas:1:common#/$defs/nonexistent"',
        )
        self.assert_failed(report, "ref:")

    def test_missing_approval_hash_is_detected(self) -> None:
        report = self.run_fixture(
            '    "bound_hash": "sha256:9db02ed91537c1ca63d6d09f9895d669ec210a1cab9859b9362592553510d8a3",\n',
            "",
        )
        self.assert_failed(report, "example:approval.requested")

    def test_meta_schema_error_is_reported(self) -> None:
        report = self.run_fixture('"title": "Budget",', '"title": "Budget", "type": 42,')
        self.assert_failed(report, "parse:")
        report = self.run_fixture('"title": "Budget",', '"title": 42,')
        self.assert_failed(report, "meta_schema:")

    def test_unknown_event_example_is_detected(self) -> None:
        report = self.run_fixture('"type": "run.created",', '"type": "run.nonexistent",')
        self.assert_failed(report, "example:run.created")

    def test_missing_snapshot_context_is_detected(self) -> None:
        report = self.run_fixture(
            '"workspace_id": "ws_acme", "run_id": "RUN-001", "task_id": null,',
            '"workspace_id": "ws_acme", "task_id": null,',
        )
        self.assert_failed(report, "fixture_schema:approval_budget")

    def test_hash_vector_drift_is_detected(self) -> None:
        report = self.run_fixture(
            '"approval_budget": "sha256:9db02ed91537c1ca63d6d09f9895d669ec210a1cab9859b9362592553510d8a3"',
            '"approval_budget": "sha256:' + "a" * 64 + '"',
        )
        self.assert_failed(report, "fixture_digest:approval_budget")

    def test_evidence_candidate_drift_is_detected(self) -> None:
        report = self.run_fixture(
            '"candidate_commit": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
            '"candidate_commit": "ffffffffffffffffffffffffffffffffffffffff"',
        )
        self.assert_failed(report, "probe:approval_example_git.merge")

    def test_semantic_decision_content_drift_is_detected(self) -> None:
        report = self.run_fixture(
            "Keep transport calls behind the adapter boundary.",
            "Change the base decision without issuing a new semantic evidence ref.",
        )
        self.assert_failed(report, "probe:approval_example_git.merge")

    def test_arbitration_must_bind_conflict_evidence(self) -> None:
        report = self.run_fixture(
            '"checksum": "sha256:7186b9d33078268d83422acdf59d197ca6f0dd9e0ee607014b611400860cce2f"',
            '"checksum": "sha256:' + "f" * 64 + '"',
        )
        self.assert_failed(report, "arbitration_decision_matches_semantic_evidence")

    def test_lost_snapshot_fixture_is_detected(self) -> None:
        report = self.run_fixture("<!-- fixture:approval_budget -->", "<!-- untagged -->")
        self.assert_failed(report, "approval_fixtures_present")

    def test_reordered_merge_gate_is_detected(self) -> None:
        report = self.run_fixture("5. Gate build/lint/test", "5. Skip build/lint/test")
        self.assert_failed(report, "documented_merge_order")

    def test_batch_item_receipt_hash_mismatch_is_detected(self) -> None:
        report = self.run_fixture(
            '"batch_hash": "sha256:af70e4125e2376b0c361265f48d3f87969de9caad43e8ec6c8a8d2ab77468720"',
            '"batch_hash": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
        )
        self.assert_failed(report, "batch_item_receipt_matches_manifest")

    def test_digest_mode_rejects_non_high_risk(self) -> None:
        report = self.run_fixture(
            '"delivery_mode": "immediate"',
            '"delivery_mode": "digest"',
        )
        self.assert_failed(report, "example:approval.requested")

    def test_cas_without_expected_base_is_detected(self) -> None:
        report = self.run_fixture(
            "git update-ref --no-deref <target_ref> <candidate_commit> <expected_base>",
            "git update-ref --no-deref <target_ref> <candidate_commit>",
        )
        self.assert_failed(report, "documented_expected_base_cas")

    def test_duplicate_snapshot_key_is_detected(self) -> None:
        report = self.run_fixture(
            '"current_limits": { "max_cost_usd": 1.0 },',
            '"current_limits": {}, "current_limits": { "max_cost_usd": 1.0 },',
        )
        self.assert_failed(report, "parse:")

    def test_relaxed_snapshot_required_fields_are_detected(self) -> None:
        report = self.run_fixture(
            '"policy_hash", "contract_hash", "inputs"],',
            '"policy_hash", "inputs"],',
        )
        self.assert_failed(report, "probe:snapshot_approval_budget_missing_contract_hash")

    def test_shifted_number_with_valid_anchor_is_detected(self) -> None:
        report = self.run_fixture(
            "[5A.22 — Compiler Gate]", "[5A.21 — Compiler Gate]",
            "06-permissions-approvals-roles.md",
        )
        self.assert_failed(report, "link_section:")

    def test_wrong_but_existing_anchor_is_detected(self) -> None:
        report = self.run_fixture(
            "#5a18-scheduler", "#5a17-network-failure-handling-deterministic-go-runtime",
            "08-runtime-architecture.md",
        )
        self.assert_failed(report, "link_section:")

    def test_nonexistent_section_is_detected(self) -> None:
        report = self.run_fixture("5A.1–5A.28", "5A.1–5A.99", "README.md")
        self.assert_failed(report, "section_reference:")

    def test_missing_document_is_detected(self) -> None:
        report = self.run_fixture(
            "02-ai-control-plane.md#5a25-semantic-retrieval",
            "missing.md#5a25-semantic-retrieval", "05-artifacts-memory-tools.md",
        )
        self.assert_failed(report, "document_link:")

    def test_missing_anchor_is_detected(self) -> None:
        report = self.run_fixture(
            "#5a25-semantic-retrieval", "#missing-heading", "05-artifacts-memory-tools.md",
        )
        self.assert_failed(report, "document_anchor:")

    def test_legacy_event_names_are_detected(self) -> None:
        for filename, before, after in (
            ("01-vision-and-core.md", "tool.call_started", "tool.started"),
            ("01-vision-and-core.md", "agent.started", "agent.status_changed"),
            ("04-communication-and-events.md", "agent.started", "agent.start"),
            ("04-communication-and-events.md", "task.created", "task.create"),
            ("04-communication-and-events.md", "tool.call_requested", "tool.request"),
            ("04-communication-and-events.md", "approval.requested", "approval.request"),
        ):
            with self.subTest(event=after):
                self.assert_failed(self.run_fixture(before, after, filename), "document_event:")

    def test_workspace_fence_ending_early_is_detected(self) -> None:
        report = self.run_fixture(
            "# Session Policy & Prompt Caching (I23)",
            "```\n\n# Session Policy & Prompt Caching (I23)",
            "07-dashboard-config-storage.md",
        )
        self.assert_failed(report, "workspace_example:")

    def test_unclosed_fences_are_detected(self) -> None:
        for fence in ("```", "~~~~"):
            with self.subTest(fence=fence):
                checks = []
                AUDIT.markdown_parts(
                    f"# 36. Config\n{fence}yaml\nsession_policy: {{}}\n", "example.md",
                    lambda *args: checks.append(args),
                )
                self.assertEqual(checks[0][0], "fences_closed:example.md")
                self.assertFalse(checks[0][1])

    def test_incomplete_workspace_example_is_detected(self) -> None:
        for field in ("providers", "models", "tool_capabilities", "session_policy"):
            with self.subTest(field=field):
                report = self.run_fixture(f"\n{field}:\n", f"\nmissing_{field}:\n", "07-dashboard-config-storage.md")
                self.assert_failed(report, "workspace_example:")

    def test_heading_index_ignores_code_and_preserves_section_ownership(self) -> None:
        checks = []
        prose, _ = AUDIT.markdown_parts(
            "# 5A.22 Cheap Path\n```yaml\n# 5A.99 Not a heading\n```\n"
            "### Compiler Gate\n### Compiler Gate\n## 5A.23 Next\n### Compiler Gate\n",
            "example.md", lambda *args: checks.append(args),
        )
        anchors = AUDIT.heading_index(prose)
        self.assertNotIn("5a99-not-a-heading", anchors)
        self.assertEqual(anchors["compiler-gate"], "5A.22")
        self.assertEqual(anchors["compiler-gate-1"], "5A.22")
        self.assertEqual(anchors["compiler-gate-2"], "5A.23")
        self.assertTrue(checks[0][1])

if __name__ == "__main__":
    unittest.main()
