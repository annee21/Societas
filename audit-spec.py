#!/usr/bin/env python3
"""Static audit of the Markdown contracts; not a Societas runtime harness."""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator
from urllib.parse import unquote

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
import rfc8785
import yaml

PREFIX = "urn:societas:1:"
FENCE = re.compile(r"^```(json|yaml)\s*\n(.*?)^```\s*$", re.M | re.S)
TAG = re.compile(r"<!-- (schema|schemas|example|fixture):([\w.]+) -->\s*$")
ROW = re.compile(r"^\| `([\w.]+)` \| `(\w+)` \|", re.M)
NUMBER = re.compile(r"^#{1,6} (\d+[A-Z]?(?:\.\d+)*)\.? ", re.M)
SECTION_REF = re.compile(r"(?<![\w.])(?:5A|72A)\.\d+(?:\.\d+)*(?![\w.])")
LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
TASK_EVENTS = {
    "task.paused", "task.resumed", "task.interrupted",
    "task.rebase_conflict", "task.semantic_conflict", "task.contract_changed",
}


def markdown_parts(text: str, filename: str, check: Any) -> tuple[str, list[tuple[str, str, int, str]]]:
    """Keep line numbers while excluding fenced code from prose/heading checks."""
    lines = text.splitlines(keepends=True)
    prose = list(lines)
    blocks: list[tuple[str, str, int, str]] = []
    marker = ""
    language = tag = ""
    start = 0
    for index, line in enumerate(lines):
        fence = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip())
        if marker:
            prose[index] = "\n"
            if (fence and fence[1][0] == marker[0] and len(fence[1]) >= len(marker)
                    and not fence[2].strip()):
                blocks.append((language, "".join(lines[start + 1:index]), start + 1, tag))
                marker = ""
        elif fence:
            marker, language = fence[1], fence[2].strip()
            start = index
            tag = lines[index - 1].strip() if index else ""
            prose[index] = "\n"
    check(f"fences_closed:{filename}", not marker, f"unclosed fence at line {start + 1}" if marker else "")
    return re.sub(r"<!--.*?-->", lambda match: "\n" * match[0].count("\n"), "".join(prose), flags=re.S), blocks


def heading_index(prose: str) -> dict[str, str]:
    """GitHub-style anchors mapped to their owning numbered section."""
    anchors: dict[str, str] = {}
    duplicates: Counter = Counter()
    stack: list[tuple[int, str]] = []
    for match in re.finditer(r"^(#{1,6}) +(.+?)\s*#*\s*$", prose, re.M):
        depth, title = len(match[1]), match[2]
        title = LINK.sub(r"\1", title)
        title = re.sub(r"<[^>]*>", "", title)
        number = re.match(r"(\d+[A-Z]?(?:\.\d+)*)\.?(?:\s|$)", title)
        while stack and stack[-1][0] >= depth:
            stack.pop()
        owner = number[1] if number else (stack[-1][1] if stack else "")
        stack.append((depth, owner))
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        anchor = slug
        while anchor in anchors:
            duplicates[slug] += 1
            anchor = f"{slug}-{duplicates[slug]}"
        anchors[anchor] = owner
    return anchors


def documentation_checks(texts: dict[str, str], mapping: dict[str, str], check: Any) -> None:
    parts = {name: markdown_parts(text, name, check) for name, text in texts.items()}
    headings = {name: heading_index(prose) for name, (prose, _) in parts.items()}
    sections = {number for anchors in headings.values() for number in anchors.values() if number}
    for filename, (prose, blocks) in sorted(parts.items()):
        for number in sorted(set(SECTION_REF.findall(prose))):
            check(f"section_reference:{filename}:{number}", number in sections, number)
        for match in LINK.finditer(prose):
            label, target = match.groups()
            if not (target.startswith("#") or re.match(r"(?:\./)?[^:#]+\.md(?:#|$)", target)):
                continue
            destination, _, anchor = target.partition("#")
            destination = destination.removeprefix("./") or filename
            location = f"{filename}:{prose[:match.start()].count(chr(10)) + 1}"
            check(f"document_link:{location}:{target}", destination in texts, target)
            if destination not in texts or not anchor:
                continue
            anchor = unquote(anchor)
            check(f"document_anchor:{location}:{target}", anchor in headings[destination], target)
            if anchor not in headings[destination]:
                continue
            numbers = re.findall(r"(?<![\w.])((?:5A|72A)\.\d+(?:\.\d+)*|[§#]\d+(?:\.\d+)*)", label)
            for number in numbers:
                number = number.lstrip("§#")
                owner = headings[destination][anchor]
                check(f"link_section:{location}:{number}", number == owner,
                      {"label": number, "target_section": owner, "target": target})
        for language, body, line, tag in blocks:
            if tag == "<!-- event-types -->":
                check(f"event_list_format:{filename}:{line}", language == "text")
                for event_type in filter(None, map(str.strip, body.splitlines())):
                    check(f"document_event:{filename}:{line}:{event_type}", event_type in mapping, event_type)
            if tag == "<!-- example:workspace.yaml -->":
                required = {"version", "workspace", "server", "transport", "providers", "models",
                            "agents", "tool_capabilities", "escalation_lead", "toolchain", "risk", "session_policy"}
                try:
                    config = yaml.safe_load(body)
                    present = set(config) if isinstance(config, dict) else set()
                    check(f"workspace_example:{filename}:{line}", language == "yaml" and required <= present,
                          {"missing": sorted(required - present)})
                except yaml.YAMLError as error:
                    check(f"workspace_example:{filename}:{line}", False, str(error))


def objects(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise ValueError(f"non-JSON numeric constant: {value}")


def boundary_errors(
    event: dict[str, Any],
    schemas: dict[str, dict[str, Any]],
    mapping: dict[str, str],
    registry: Registry,
) -> list[str]:
    """Reference checks for documented wire rules only (no auth/SQLite)."""
    errors = [
        f"envelope: {error.message}"
        for error in Draft202012Validator(
            schemas[PREFIX + "envelope"], registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(event)
    ]
    event_type = event.get("type", "")
    if event_type not in mapping:
        return errors + ["unknown event type"]
    payload = event.get("payload")
    errors.extend(
        f"payload: {error.message}"
        for error in Draft202012Validator(
            schemas[PREFIX + mapping[event_type]], registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(payload)
    )
    if not isinstance(payload, dict):
        return errors
    if event_type != "run.created" and "causation_id" not in event:
        errors.append("non-root event missing causation_id (I8)")
    if event_type in TASK_EVENTS and "task_id" not in event:
        errors.append("task lifecycle event missing task_id")
    if event_type == "task.paused":
        requested = payload.get("phase") == "requested"
        expected_sender = "human:user" if requested else "system:orchestrator"
        expected_target = "system:orchestrator" if requested else "topic:all"
        if event.get("from") != expected_sender or event.get("to") != expected_target:
            errors.append("pause phase/sender/target mismatch")
    if event_type == "task.resumed":
        if event.get("from") != "system:orchestrator":
            errors.append("resume sender must be orchestrator")
        if not str(event.get("to", "")).startswith("agent:"):
            errors.append("resume must target an agent (owner requires runtime check)")
    if event_type == "approval.requested":
        reference = payload.get("snapshot_ref")
        if isinstance(reference, dict) and reference.get("checksum") != payload.get("bound_hash"):
            errors.append("snapshot checksum must equal bound_hash")
    if event_type == "approval.batch_submitted":
        reference = payload.get("batch_ref")
        if isinstance(reference, dict) and reference.get("checksum") != payload.get("batch_hash"):
            errors.append("batch checksum must equal batch_hash")
        if event.get("from") != "human:user" or event.get("to") != "system:orchestrator":
            errors.append("batch submit sender/target mismatch")
    if event_type == "approval.invalidated":
        if event.get("from") != "system:orchestrator" or event.get("to") != "human:user":
            errors.append("invalidation sender/target mismatch (not an auth check)")
    try:
        limit = 16000 if event_type == "tool.call_completed" else 8000
        if len(rfc8785.dumps(payload)) > limit:
            errors.append(f"aggregate payload exceeds {limit} UTF-8 bytes")
    except (ValueError, TypeError) as error:
        errors.append(f"payload serialization: {error}")
    return errors


def snapshot_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def semantic_input_errors(
    evidence: dict[str, Any],
    artifacts: dict[tuple[str, int], bytes],
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
    *,
    current: dict[str, Any] | None = None,
) -> list[str]:
    """Validate exact-version decision registry inputs; not model quality/provenance."""
    errors: list[str] = []
    index_ref = evidence.get("decision_index_ref", {})
    index_bytes = artifacts.get((index_ref.get("artifact_id"), index_ref.get("version")))
    if index_bytes is None or "sha256:" + hashlib.sha256(index_bytes).hexdigest() != index_ref.get("checksum"):
        return ["semantic decision index version/checksum unavailable or changed"]
    try:
        index = json.loads(index_bytes, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        validator = Draft202012Validator(
            schemas[PREFIX + "semantic_decision_index"], registry=registry,
            format_checker=FormatChecker(),
        )
        index_errors = list(validator.iter_errors(index))
        if index_errors:
            return [f"semantic decision index: {error.message}" for error in index_errors]
        if index_bytes != rfc8785.dumps(index):
            errors.append("semantic decision index is not canonical JCS")
        binding = evidence["binding"]
        candidate = binding["candidate"]
        for field, expected in (
            ("workspace_id", binding["workspace_id"]), ("run_id", binding["run_id"]),
            ("repo_id", candidate["repo_id"]), ("target_ref", candidate["target_ref"]),
            ("base_commit", candidate["expected_base"]),
            ("candidate_commit", candidate["candidate_commit"]),
        ):
            if index[field] != expected:
                errors.append(f"semantic decision index binding mismatch: {field}")
        for prefix in ("base", "candidate"):
            key = prefix + "_decisions"
            count = index[prefix + "_decision_count"]
            refs = index[key]
            ids = [reference["artifact_id"] for reference in refs]
            if count != len(refs):
                errors.append(f"{key} count does not match registry manifest")
            if ids != sorted(ids, key=lambda value: value.encode("utf-16-be")):
                errors.append(f"{key} must be UTF-16 sorted")
            for reference in refs:
                content = artifacts.get((reference["artifact_id"], reference["version"]))
                if content is None or "sha256:" + hashlib.sha256(content).hexdigest() != reference["checksum"]:
                    errors.append(f"{key} artifact version/checksum unavailable or changed")
        expected_refs = [
            *({"role": "base", "artifact_ref": ref} for ref in index["base_decisions"]),
            *({"role": "candidate", "artifact_ref": ref} for ref in index["candidate_decisions"]),
        ]
        actual_refs = evidence.get("decision_refs", [])
        actual_ids = [entry["artifact_ref"]["artifact_id"] for entry in actual_refs]
        if actual_refs != expected_refs:
            errors.append("semantic decision refs differ from trusted exact-version index")
        if actual_ids != sorted(actual_ids, key=lambda value: value.encode("utf-16-be")):
            errors.append("semantic decision refs must be UTF-16 sorted")
        if "findings_ref" in evidence:
            reference = evidence["findings_ref"]
            content = artifacts.get((reference["artifact_id"], reference["version"]))
            if content is None or "sha256:" + hashlib.sha256(content).hexdigest() != reference["checksum"]:
                errors.append("semantic findings version/checksum unavailable or changed")
        if current is not None:
            fields = ("semantic_recipe_hash", "decision_index_ref", "decision_refs", "findings_ref")
            if any(evidence.get(field) != current.get(field) for field in fields):
                errors.append("live semantic recipe/decision manifest changed")
    except (ValueError, TypeError, UnicodeError, KeyError) as error:
        errors.append(f"semantic input serialization: {error}")
    return errors


def approval_errors(
    request: dict[str, Any],
    artifacts: dict[tuple[str, int], bytes],
    schemas: dict[str, dict[str, Any]],
    registry: Registry,
    *,
    current_snapshot: dict[str, Any] | None = None,
    grant: dict[str, Any] | None = None,
    status: str = "pending",
    now: str | None = None,
    contract_current: bool = True,
    current_semantic: dict[str, Any] | None = None,
) -> list[str]:
    """Reference snapshot predicate over fixtures, not an execution/CAS engine."""
    errors = boundary_errors(request, schemas, {"approval.requested": "approval_requested"}, registry)
    if errors:
        return errors
    payload = request["payload"]
    reference = payload["snapshot_ref"]
    content = artifacts.get((reference["artifact_id"], reference["version"]))
    if content is None:
        return ["snapshot artifact version unavailable"]
    try:
        snapshot = json.loads(content, object_pairs_hook=unique_object, parse_constant=invalid_constant)
        snapshot_errors = list(Draft202012Validator(
            schemas[PREFIX + "approval_snapshot"], registry=registry,
            format_checker=FormatChecker(),
        ).iter_errors(snapshot))
        if snapshot_errors:
            return [f"snapshot: {error.message}" for error in snapshot_errors]
        if content != rfc8785.dumps(snapshot) or snapshot_digest(snapshot) != payload["bound_hash"]:
            errors.append("snapshot bytes/digest mismatch")
        if current_snapshot is not None:
            current_errors = list(Draft202012Validator(
                schemas[PREFIX + "approval_snapshot"], registry=registry,
                format_checker=FormatChecker(),
            ).iter_errors(current_snapshot))
            if current_errors or snapshot_digest(current_snapshot) != payload["bound_hash"]:
                errors.append("live bound input changed")
        for field in ("workspace_id", "run_id", "task_id"):
            if snapshot[field] != request.get(field):
                errors.append(f"snapshot envelope mismatch: {field}")
        if snapshot["action"] != payload["action"]:
            errors.append("snapshot action mismatch")
        if status not in {"pending", "granted"}:
            errors.append("approval no longer valid")
        if not contract_current:
            errors.append("task contract stale")
        if now and payload.get("expires_at"):
            if datetime.fromisoformat(now.replace("Z", "+00:00")) >= datetime.fromisoformat(
                payload["expires_at"].replace("Z", "+00:00"),
            ):
                errors.append("approval expired")
        if grant is not None:
            errors.extend(
                f"grant: {error.message}" for error in Draft202012Validator(
                    schemas[PREFIX + "approval_granted"], registry=registry,
                    format_checker=FormatChecker(),
                ).iter_errors(grant)
            )
            for field in ("approval_id", "bound_hash"):
                if grant.get(field) != payload[field]:
                    errors.append(f"grant request mismatch: {field}")
            if "budget_override" in grant:
                if snapshot["action"] != "budget.increase" or (
                    rfc8785.dumps(grant["budget_override"]) !=
                    rfc8785.dumps(snapshot["inputs"]["proposed_limits"])
                ):
                    errors.append("unbound budget override")
        if snapshot["action"] == "budget.increase":
            scope = snapshot["inputs"]["scope"]
            scope_field = {"workspace": "workspace_id", "run": "run_id", "task": "task_id"}.get(scope)
            if scope_field and snapshot["inputs"]["target_id"] != snapshot[scope_field]:
                errors.append("budget scope/target identity mismatch")
        if snapshot["action"] == "tool.execute":
            resource_ids = [resource["resource_id"] for resource in snapshot["inputs"]["resources"]]
            if len(set(resource_ids)) != len(resource_ids) or resource_ids != sorted(
                resource_ids, key=lambda value: value.encode("utf-16-be"),
            ):
                errors.append("resource IDs must be unique and sorted by UTF-16 code units")
        if snapshot["action"] == "git.merge":
            candidate = snapshot["inputs"]["candidate"]
            oid_lengths = {len(candidate[field]) for field in ("expected_base", "candidate_commit", "candidate_tree")}
            if len(oid_lengths) != 1:
                errors.append("mixed Git object formats")
            binding = {field: snapshot[field] for field in (
                "workspace_id", "run_id", "task_id", "policy_hash", "contract_hash",
            )}
            binding["candidate"] = candidate
            for kind, input_key, result in (
                ("semantic_rebase", "semantic_evidence", "pass"),
                ("gate", "gate_evidence", "pass"),
                ("review", "review_evidence", "approve"),
            ):
                evidence_ref = snapshot["inputs"][input_key]
                evidence_bytes = artifacts.get((evidence_ref["artifact_id"], evidence_ref["version"]))
                if evidence_bytes is None:
                    errors.append(f"{kind} artifact version unavailable")
                    continue
                evidence = json.loads(evidence_bytes, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                evidence_errors = list(Draft202012Validator(
                    schemas[PREFIX + "merge_evidence"], registry=registry,
                    format_checker=FormatChecker(),
                ).iter_errors(evidence))
                if evidence_errors:
                    errors.extend(f"{kind}: {error.message}" for error in evidence_errors)
                    continue
                checksum = "sha256:" + hashlib.sha256(evidence_bytes).hexdigest()
                if checksum != evidence_ref["checksum"]:
                    errors.append(f"{kind} artifact checksum mismatch")
                if rfc8785.dumps(evidence["binding"]) != rfc8785.dumps(binding):
                    errors.append(f"{kind} candidate/context mismatch")
                if evidence["kind"] != kind or evidence["result"] != result:
                    errors.append(f"{kind} evidence not accepted")
                if kind == "semantic_rebase":
                    errors.extend(semantic_input_errors(
                        evidence, artifacts, schemas, registry, current=current_semantic,
                    ))
    except (ValueError, TypeError, UnicodeError) as error:
        errors.append(f"approval serialization: {error}")
    return errors


def audit(root: Path, baseline_ref: str | None) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: Any = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    texts = {path.name: path.read_text(encoding="utf-8") for path in root.glob("*.md")}
    canonical = texts.get("10-contracts-mvp-roadmap.md", "")
    check("canonical_document_present", bool(canonical))
    schemas: dict[str, dict[str, Any]] = {}
    examples: list[tuple[str, dict[str, Any]]] = []
    fixtures: dict[str, dict[str, Any]] = {}
    counts: Counter = Counter()
    for filename, text in sorted(texts.items()):
        for match in FENCE.finditer(text):
            language, body = match.groups()
            counts[language] += 1
            location = f"{filename}:{text[:match.start()].count(chr(10)) + 1}"
            try:
                value = (
                    json.loads(body, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                    if language == "json" else yaml.safe_load(body)
                )
                check(f"parse:{language}:{location}", True)
            except (ValueError, yaml.YAMLError) as error:
                check(f"parse:{language}:{location}", False, str(error))
                continue
            tag = TAG.search(text[:match.start()])
            if language != "json" or not tag or filename != "10-contracts-mvp-roadmap.md":
                continue
            kind, name = tag.groups()
            if kind == "fixture":
                check(f"fixture_is_object:{name}", isinstance(value, dict))
                check(f"fixture_unique:{name}", name not in fixtures)
                if isinstance(value, dict):
                    fixtures[name] = value
                continue
            if kind == "example":
                check(f"example_is_object:{location}", isinstance(value, dict))
                if isinstance(value, dict):
                    examples.append((name, value))
                continue
            definitions = value if kind == "schemas" else [value]
            check(f"schema_collection:{location}", isinstance(definitions, list))
            if not isinstance(definitions, list):
                continue
            for definition in definitions:
                valid = isinstance(definition, dict) and "$id" in definition
                check(f"schema_has_id:{location}", valid)
                if not valid:
                    continue
                schema_id = definition["$id"]
                check(f"unique_schema_id:{schema_id}", schema_id not in schemas)
                schemas[schema_id] = definition
                try:
                    Draft202012Validator.check_schema(definition)
                    check(f"meta_schema:{schema_id}", True)
                except SchemaError as error:
                    check(f"meta_schema:{schema_id}", False, str(error))

    check("schema_markers_not_lost", len(schemas) >= 47, len(schemas))
    check("example_markers_not_lost", len(examples) >= 14, len(examples))
    registry: Registry = Registry().with_resources(
        (schema_id, Resource.from_contents(schema, default_specification=DRAFT202012))
        for schema_id, schema in schemas.items()
    )
    refs = 0
    for schema_id, schema in schemas.items():
        for node in objects(schema):
            if "$ref" not in node:
                continue
            refs += 1
            try:
                registry.resolver(schema_id).lookup(node["$ref"])
                check(f"ref:{schema_id}:{refs}", True)
            except Exception as error:
                check(f"ref:{schema_id}:{refs}", False, str(error))

    registry_section = canonical.split("## 72A.7 Event Registry")[-1].split("## 72A.8")[0]
    rows = ROW.findall(registry_section)
    mapping = dict(rows)
    check("registry_types_unique", len(mapping) == len(rows))
    check("registry_rows_not_lost", len(mapping) >= 42, len(mapping))
    documentation_checks(texts, mapping, check)
    for event_type, schema_name in mapping.items():
        check(f"registry:{event_type}", PREFIX + schema_name in schemas)
    reachable = {PREFIX + "envelope"} | {PREFIX + name for name in mapping.values()}
    while True:
        expanded = reachable | {
            node["$ref"].split("#")[0] or schema_id
            for schema_id in reachable if schema_id in schemas
            for node in objects(schemas[schema_id]) if "$ref" in node
        }
        if expanded == reachable:
            break
        reachable = expanded
    check("no_orphan_schemas", not (set(schemas) - reachable), sorted(set(schemas) - reachable))
    dependencies_ok = all(schema_id in schemas for schema_id in reachable) and not any(
        not entry["passed"] and entry["name"].startswith(
            ("parse:", "meta_schema:", "ref:", "unique_schema_id:")
        )
        for entry in checks
    )
    for name, event in examples:
        check(f"example_type:{name}", event.get("type") == name)
        try:
            errors = boundary_errors(event, schemas, mapping, registry)
            check(f"example:{name}", not errors, errors)
        except Exception as error:
            check(f"example:{name}", False, str(error))
    probe_examples = {"approval.requested", "task.created"}
    if dependencies_ok and probe_examples <= {name for name, _ in examples}:
        probes(schemas, mapping, registry, examples, check)
    else:
        check("probes_runnable", False, "missing schema dependencies or fixture examples")
    approval_fixtures = {
        "approval_budget", "approval_merge", "approval_tool",
        "approval_batch", "approval_hash_vectors", "merge_semantic_rebase", "merge_gate", "merge_review",
        "semantic_decision_base", "semantic_decision_candidate", "semantic_decision_index",
        "approval_batch_item_receipt_granted", "approval_batch_item_receipt_skipped",
        "merge_receipt", "semantic_arbitration_decision", "semantic_conflict_evidence",
    }
    check("approval_fixtures_present", approval_fixtures <= fixtures.keys())
    if dependencies_ok and approval_fixtures <= fixtures.keys():
        try:
            approval_probes(schemas, registry, examples, fixtures, check)
        except (ValueError, TypeError, UnicodeError, KeyError) as error:
            check("approval_probes_runnable", False, str(error))
    else:
        check("approval_probes_runnable", False, "missing schema dependencies or approval fixtures")
    merge_flow = canonical.split("### Serial Merge: Final Candidate Binding")[-1].split("### Output besar")[0]
    markers = [
        "2. Rebase branch task", "5. Gate build/lint/test", "6. Semantic Rebase PASS",
        "7. review.requested/completed", "8. Persist snapshot JCS",
        "9. Tepat sebelum integrasi", "10. Verifikasi candidate_commit",
    ]
    positions = [merge_flow.find(marker) for marker in markers]
    check("documented_merge_order", all(position >= 0 for position in positions) and positions == sorted(positions))
    conflict = merge_flow.find("conflict -> task.rebase_conflict -> Engineer")
    approval = merge_flow.find("approval.requested")
    check("documented_conflict_before_approval", 0 <= conflict < approval)
    check("documented_expected_base_cas", "git update-ref --no-deref <target_ref> <candidate_commit> <expected_base>" in merge_flow)

    state_section = canonical.split("## 72A.6 Task State Machine")[-1].split("## 72A.7")[0]
    transitions = re.findall(
        r"^\| `(\w+)` \| `(\w+)` \| .*? \| `([\w.]+)` \|$", state_section, re.M
    )
    task_schema = schemas.get(PREFIX + "task", {})
    states = set(task_schema.get("properties", {}).get("status", {}).get("enum", []))
    for before, after, event_type in transitions:
        check(f"transition:{before}:{after}", before in states and after in states and event_type in mapping)
    check("terminal_states_have_no_exit", not any(
        before in {"completed", "failed", "cancelled"} for before, _, _ in transitions
    ))
    pairs = {(before, after) for before, after, _ in transitions}
    recovery_pairs = {
        ("running", "interrupted"), ("pausing", "interrupted"),
        ("pausing", "failed"), ("pausing", "cancelled"), ("interrupted", "cancelled"),
    }
    check("pause_recovery_transitions", recovery_pairs <= pairs)
    for error_code in ("SEARCH_BLOCK_NOT_FOUND", "SEARCH_BLOCK_AMBIGUOUS", "REBASE_CONFLICT", "APPROVAL_BINDING_INVALID"):
        catalog = canonical.split("## 72A.9")[-1].split("## 72A.10")[0]
        check(f"error_catalog:{error_code}", f"| `{error_code}` |" in catalog)

    if baseline_ref:
        for filename, text in sorted(texts.items()):
            if not re.match(r"^\d\d-", filename):
                continue
            previous = subprocess.run(
                ["git", "show", f"{baseline_ref}:{filename}"], cwd=root,
                text=True, capture_output=True, check=False,
            )
            if previous.returncode:
                check(f"numbering_baseline:{filename}", False, previous.stderr.strip())
                continue
            original = NUMBER.findall(previous.stdout)
            current = NUMBER.findall(text)
            iterator = iter(current)
            check(f"numbering_preserved:{filename}", all(
                any(candidate == number for candidate in iterator) for number in original
            ), {"baseline": original, "current": current})

    failures = [entry for entry in checks if not entry["passed"]]
    return {
        "audit_kind": "replacement-static-contract-audit",
        "counts": {
            **counts, "schemas": len(schemas), "refs": refs, "registry": len(mapping),
            "examples": len(examples), "fixtures": len(fixtures), "checks": len(checks), "failures": len(failures),
        },
        "passed": not failures,
        "checks": checks,
        "limitations": [
            "Original review audit assets were not supplied; counts/probes may differ.",
            "YAML syntax and tagged workspace example completeness only; no config schema was supplied.",
            "Prose 5A/72A reference existence, local Markdown links/anchors and numbered link labels checked; "
            "bare reference intent is not inferred. Only tagged event-type lists are checked against the registry.",
            "Reference boundary probes are not runtime integration tests.",
            "Approval fixture predicates/document-order checks do not execute rebase, gates, "
            "review, Git-ref CAS, scope consumption, or live resource-version checks.",
            "No authentication, ownership, SQLite CAS/outbox/ledger, crash injection, "
            "provider/tool reconciliation, memory GC, Git broker, or OS sandbox tested.",
            "Audit pass does not close pending design findings or prove MVP acceptance.",
        ],
    }


def probes(schemas: dict, mapping: dict, registry: Registry, examples: list, check: Any) -> None:
    template = deepcopy(examples[0][1])
    template.update({
        "task_id": "TASK-001", "causation_id": template["id"],
        "from": "system:orchestrator", "to": "agent:engineer",
    })

    def event_probe(name: str, event_type: str, payload: dict, accepted: bool, **fields: Any) -> None:
        event = {**template, "type": event_type, "payload": payload, **fields}
        errors = boundary_errors(event, schemas, mapping, registry)
        check(f"probe:{name}", (not errors) == accepted, {"expected_accept": accepted, "errors": errors})

    def schema_probe(name: str, schema_name: str, value: dict, accepted: bool) -> None:
        valid = Draft202012Validator(
            schemas[PREFIX + schema_name], registry=registry, format_checker=FormatChecker(),
        ).is_valid(value)
        check(f"probe:{name}", valid == accepted, {"expected_accept": accepted, "schema_accept": valid})

    event_probe("unknown_type", "task.nonexistent", {}, False)
    event_probe("extra_payload_field", "task.started", {"attempt": 1, "extra": True}, False)
    event_probe("missing_envelope_field", "task.started", {"attempt": 1}, False, run_id=None)
    pause = {"phase": "requested", "initiated_by": "human:user", "pause_deadline": "2026-10-06T18:00:00Z"}
    event_probe("pause_requested", "task.paused", pause, True, **{"from": "human:user", "to": "system:orchestrator"})
    event_probe("pause_wrong_sender", "task.paused", pause, False)
    event_probe("pause_completed", "task.paused", {**pause, "phase": "completed"}, True, to="topic:all")
    event_probe("pause_missing_deadline", "task.paused", {"phase": "completed", "initiated_by": "human:user"}, False)
    resume = {"initiated_by": "human:user", "from_status": "paused"}
    event_probe("resume", "task.resumed", resume, True)
    event_probe("resume_wrong_sender", "task.resumed", resume, False, **{"from": "human:user"})
    event_probe("interrupted_pausing", "task.interrupted", {"previous_status": "pausing", "reason": "restart"}, True)
    hashes = {"old_hash": "sha256:" + "a" * 64, "new_hash": "sha256:" + "b" * 64}
    event_probe("contract_invalidated", "task.contract_changed", {**hashes, "phase": "invalidated", "required_actions": ["recodegen", "rereview"]}, True)
    event_probe("contract_missing_codegen", "task.contract_changed", {**hashes, "phase": "invalidated", "required_actions": ["rereview"]}, False)
    event_probe("contract_repinned", "task.contract_changed", {**hashes, "phase": "repinned"}, True)
    event_probe("rebase_conflict", "task.rebase_conflict", {"base_ref": "a" * 40, "conflict_files": ["src/main.go"]}, True)
    event_probe("empty_conflict", "task.rebase_conflict", {"base_ref": "a" * 40, "conflict_files": []}, False)
    schema_probe("budget_rebuttals", "budget", {"max_rebuttals": 2}, True)
    schema_probe("negative_rebuttals", "budget", {"max_rebuttals": -1}, False)
    approval = next(event["payload"] for name, event in examples if name == "approval.requested")
    schema_probe("approval_missing_hash", "approval_requested", {key: value for key, value in approval.items() if key != "bound_hash"}, False)
    schema_probe("raw_git_sha_not_bound_hash", "approval_requested", {**approval, "bound_hash": "a" * 40}, False)
    task = next(event["payload"]["task"] for name, event in examples if name == "task.created")
    schema_probe("paused_task_without_deadline", "task", {**task, "status": "paused"}, False)
    schema_probe("paused_task_with_deadline", "task", {**task, "status": "paused", "pause_deadline": pause["pause_deadline"]}, True)
    schema_probe("pinned_task_missing_freshness", "task", {**task, "contract_hash": hashes["new_hash"]}, False)
    tool_id = "tc_01J9ZB75QCACYADGWFKD86P7W1"
    error = {"code": "TOOL_TIMEOUT", "category": "TIMEOUT", "message": "response lost", "retryable": False}
    failed = {"tool_call_id": tool_id, "error": error}
    event_probe("tool_unknown_outcome", "tool.call_failed", {**failed, "outcome": "outcome_unknown"}, True)
    event_probe("tool_not_started", "tool.call_failed", {**failed, "outcome": "not_started"}, True)
    event_probe("tool_missing_outcome", "tool.call_failed", failed, False)
    request: dict[str, Any] = {"tool_call_id": tool_id, "tool": "filesystem.read", "arguments": {"note": ""}}
    request_size = len(rfc8785.dumps(request))
    for size, accepted in ((8000, True), (8001, False)):
        event_probe(
            f"default_exact_size_{size}", "tool.call_requested",
            {**request, "arguments": {"note": "x" * (size - request_size)}}, accepted,
        )
    completed: dict[str, Any] = {"tool_call_id": tool_id, "status": "ok", "duration_ms": 1}
    empty_size = len(rfc8785.dumps({**completed, "output": ""}))
    for size, accepted in ((16000, True), (16001, False)):
        event_probe(f"tool_exact_size_{size}", "tool.call_completed", {**completed, "output": "x" * (size - empty_size)}, accepted)
    event_probe("large_nested_object", "tool.call_completed", {**completed, "output": {"nested": {"text": "x" * 17000}}}, False)
    schema_probe(
        "schema_only_does_not_bound_objects", "tool_call_completed",
        {**completed, "output": {"nested": {"text": "x" * 17000}}}, True,
    )
    event_probe("aggregate_short_strings", "tool.call_completed", {**completed, "output": {"a": "x" * 9000, "b": "x" * 9000}}, False)
    event_probe("multibyte_output", "tool.call_completed", {**completed, "output": "界" * 6000}, False)


def approval_probes(
    schemas: dict, registry: Registry, examples: list,
    fixtures: dict[str, dict[str, Any]], check: Any,
) -> None:
    valid_fixtures = True
    vector_names = {
        "approval_budget", "approval_merge", "approval_tool",
        "merge_semantic_rebase", "merge_gate", "merge_review",
    }
    check("fixture_hash_vectors_complete", fixtures["approval_hash_vectors"].keys() == vector_names)
    batch_validator = Draft202012Validator(
        schemas[PREFIX + "approval_batch"], registry=registry, format_checker=FormatChecker(),
    )
    batch = fixtures["approval_batch"]
    check("fixture_schema:approval_batch", batch_validator.is_valid(batch))
    operational_fixture_schemas = {
        "approval_batch_item_receipt_granted": "approval_batch_item_receipt",
        "approval_batch_item_receipt_skipped": "approval_batch_item_receipt",
        "merge_receipt": "merge_receipt",
        "semantic_arbitration_decision": "semantic_arbitration_decision",
        "semantic_conflict_evidence": "merge_evidence",
        "semantic_decision_index": "semantic_decision_index",
    }
    for fixture_name, schema_name in operational_fixture_schemas.items():
        valid = Draft202012Validator(
            schemas[PREFIX + schema_name], registry=registry, format_checker=FormatChecker(),
        ).is_valid(fixtures[fixture_name])
        check(f"fixture_schema:{fixture_name}", valid)
        valid_fixtures = valid_fixtures and valid
    batch_items = batch.get("items", [])
    batch_ids = [item.get("approval_id") for item in batch_items]
    check(
        "approval_batch_items_unique_sorted",
        len(batch_ids) == len(set(batch_ids)) and batch_ids == sorted(batch_ids, key=lambda value: value.encode("utf-16-be")),
    )
    check("approval_batch_item_hash_bindings", all(
        item.get("snapshot_ref", {}).get("checksum") == item.get("bound_hash")
        for item in batch_items
    ))
    batch_submissions = [event for name, event in examples if name == "approval.batch_submitted"]
    check("approval_batch_submission_example_present", bool(batch_submissions))
    for event in batch_submissions:
        reference = event["payload"]["batch_ref"]
        digest_requests = {
            request["payload"]["approval_id"]: request
            for name, request in examples
            if name == "approval.requested"
            and request["payload"].get("risk") == "high"
            and request["payload"].get("delivery_mode") == "digest"
        }
        check(
            "approval_batch_example_manifest_binding",
            snapshot_digest(batch) == event["payload"]["batch_hash"] == reference["checksum"]
            and batch["workspace_id"] == event["workspace_id"]
            and batch["run_id"] == event["run_id"]
            and all(
                item["approval_id"] in digest_requests
                and item["bound_hash"] == digest_requests[item["approval_id"]]["payload"]["bound_hash"]
                and item["snapshot_ref"] == digest_requests[item["approval_id"]]["payload"]["snapshot_ref"]
                and item["task_id"] == digest_requests[item["approval_id"]].get("task_id")
                for item in batch_items
            ),
        )
    for name in sorted(vector_names):
        schema_name = "approval_snapshot" if name.startswith("approval_") else "merge_evidence"
        valid = Draft202012Validator(
            schemas[PREFIX + schema_name], registry=registry,
            format_checker=FormatChecker(),
        ).is_valid(fixtures[name])
        check(f"fixture_schema:{name}", valid)
        check(f"fixture_digest:{name}", snapshot_digest(fixtures[name]) == fixtures["approval_hash_vectors"].get(name))
        valid_fixtures = valid_fixtures and valid
    if not valid_fixtures:
        check("approval_profiles_runnable", False, "invalid snapshot/evidence fixture")
        return
    snapshot_validator = Draft202012Validator(
        schemas[PREFIX + "approval_snapshot"], registry=registry, format_checker=FormatChecker(),
    )
    for name in ("approval_budget", "approval_merge", "approval_tool"):
        snapshot = fixtures[name]
        for field in snapshot:
            missing = {key: value for key, value in snapshot.items() if key != field}
            check(f"probe:snapshot_{name}_missing_{field}", not snapshot_validator.is_valid(missing))
        check(f"probe:snapshot_{name}_extra_field", not snapshot_validator.is_valid({**snapshot, "unexpected": True}))
        for field in snapshot["inputs"]:
            missing = {**snapshot, "inputs": {key: value for key, value in snapshot["inputs"].items() if key != field}}
            check(f"probe:snapshot_{name}_missing_input_{field}", not snapshot_validator.is_valid(missing))
    unknown_profile = {**fixtures["approval_merge"], "action": "unregistered.action"}
    check("probe:snapshot_unknown_profile", not snapshot_validator.is_valid(unknown_profile))
    requests = {
        event["payload"]["action"]: event
        for name, event in examples if name == "approval.requested"
    }
    grants = [event["payload"] for name, event in examples if name == "approval.granted"]
    check("approval_examples_present", {"budget.increase", "git.merge"} <= requests.keys() and bool(grants))
    if not {"budget.increase", "git.merge"} <= requests.keys() or not grants:
        return
    artifacts: dict[tuple[str, int], bytes] = {}
    for action, name in (
        ("budget.increase", "approval_budget"),
        ("git.merge", "approval_merge"),
        ("tool.execute", "approval_tool"),
    ):
        reference = requests[action]["payload"]["snapshot_ref"]
        artifacts[(reference["artifact_id"], reference["version"])] = rfc8785.dumps(fixtures[name])
    merge = fixtures["approval_merge"]
    for kind, input_key in (
        ("semantic_rebase", "semantic_evidence"),
        ("gate", "gate_evidence"),
        ("review", "review_evidence"),
    ):
        reference = merge["inputs"][input_key]
        artifacts[(reference["artifact_id"], reference["version"])] = rfc8785.dumps(fixtures["merge_" + kind])
    decision_fixtures = {
        "base": "semantic_decision_base",
        "candidate": "semantic_decision_candidate",
    }
    for decision_ref in fixtures["merge_semantic_rebase"]["decision_refs"]:
        reference = decision_ref["artifact_ref"]
        decision_fixture = fixtures[decision_fixtures[decision_ref["role"]]]
        artifacts[(reference["artifact_id"], reference["version"])] = rfc8785.dumps(decision_fixture)
    decision_index_ref = fixtures["merge_semantic_rebase"]["decision_index_ref"]
    decision_index_bytes = rfc8785.dumps(fixtures["semantic_decision_index"])
    artifacts[(decision_index_ref["artifact_id"], decision_index_ref["version"])] = decision_index_bytes
    check(
        "semantic_decision_index_fixture_checksum",
        "sha256:" + hashlib.sha256(decision_index_bytes).hexdigest() == decision_index_ref["checksum"],
    )

    receipt = fixtures["merge_receipt"]
    candidate = merge["inputs"]["candidate"]
    merge_request = requests["git.merge"]["payload"]
    check(
        "merge_receipt_matches_approval_and_evidence",
        receipt["workspace_id"] == merge["workspace_id"]
        and receipt["run_id"] == merge["run_id"]
        and receipt["task_id"] == merge["task_id"]
        and receipt["repo_id"] == candidate["repo_id"]
        and receipt["target_ref"] == candidate["target_ref"]
        and receipt["expected_base"] == candidate["expected_base"]
        and receipt["merged_commit"] == candidate["candidate_commit"]
        and receipt["merged_tree"] == candidate["candidate_tree"]
        and receipt["approval"]["approval_id"] == merge_request["approval_id"]
        and receipt["approval"]["bound_hash"] == merge_request["bound_hash"]
        and receipt["approval"]["snapshot_ref"] == merge_request["snapshot_ref"]
        and all(receipt[key] == merge["inputs"][key] for key in (
            "semantic_evidence", "gate_evidence", "review_evidence",
        )),
    )
    arbitration = fixtures["semantic_arbitration_decision"]
    semantic = fixtures["semantic_conflict_evidence"]
    decision_refs = [item["artifact_ref"] for item in semantic["decision_refs"]]
    conflict_events = [event for name, event in examples if name == "task.semantic_conflict"]
    check(
        "arbitration_decision_matches_semantic_evidence",
        bool(conflict_events)
        and semantic["result"] == "conflict"
        and arbitration["workspace_id"] == semantic["binding"]["workspace_id"]
        and arbitration["run_id"] == semantic["binding"]["run_id"]
        and arbitration["task_id"] == semantic["binding"]["task_id"]
        and arbitration["semantic_evidence"] == conflict_events[0]["payload"]["semantic_evidence"]
        and conflict_events[0]["payload"]["semantic_evidence"] == conflict_events[0]["payload"]["blocked_evidence"]
        and all(reference in decision_refs for reference in arbitration["selected_decision_refs"])
        and conflict_events[0]["payload"]["decision_refs"] == semantic["decision_refs"],
    )
    conflict_decision_fixtures = {
        "base": fixtures["semantic_decision_base"],
        "candidate": fixtures["semantic_decision_candidate"],
    }
    check("semantic_conflict_decision_checksums", all(
        "sha256:" + hashlib.sha256(rfc8785.dumps(conflict_decision_fixtures[item["role"]])).hexdigest()
        == item["artifact_ref"]["checksum"]
        for item in semantic["decision_refs"]
    ))
    # Memory admission receipt validation: receipt must match approval/grant event ID,
    # bound hash, semantic evidence and candidate merged; validated before expiry.
    # Receipt mock is not guarantee of W06 completion.
    admission_check = (
        receipt["approval"]["bound_hash"] == merge_request["bound_hash"]
        and receipt["approval"]["approval_id"] == merge_request["approval_id"]
        and receipt["semantic_evidence"] == merge["inputs"]["semantic_evidence"]
        and receipt["merged_commit"] == candidate["candidate_commit"]
        and receipt["merged_tree"] == candidate["candidate_tree"]
        and receipt["confirmed"] is True
    )
    check("memory_admission_receipt_validates_approval_and_merge", admission_check)
    # Check that receipt grant_event_id is present and valid format
    check("memory_admission_receipt_has_grant_event_id", bool(receipt["approval"].get("grant_event_id")))
    # Check that receipt validation would fail if expiry is past
    if grants and grants[0].get("expires_at"):
        expired_receipt = deepcopy(receipt)
        expired_receipt["confirmed_at"] = "2026-10-06T09:30:00Z"
        expired_receipt["validated_at"] = "2026-10-06T09:20:00Z"
        expiry = datetime.fromisoformat(grants[0]["expires_at"].replace("Z", "+00:00"))
        confirmed = datetime.fromisoformat(expired_receipt["confirmed_at"].replace("Z", "+00:00"))
        admission_expiry_check = confirmed >= expiry
        check("memory_admission_receipt_fails_after_expiry", admission_expiry_check)
    else:
        check("memory_admission_receipt_expiry_check_skipped", True)
    batch_payload = batch_submissions[0]["payload"]
    granted_receipt = fixtures["approval_batch_item_receipt_granted"]
    batch_item = next(item for item in batch_items if item["approval_id"] == granted_receipt["approval_id"])
    check(
        "batch_item_receipt_matches_manifest",
        granted_receipt["workspace_id"] == batch["workspace_id"]
        and granted_receipt["run_id"] == batch["run_id"]
        and granted_receipt["batch_hash"] == batch_payload["batch_hash"]
        and granted_receipt["batch_ref"] == batch_payload["batch_ref"]
        and granted_receipt["bound_hash"] == batch_item["bound_hash"]
        and granted_receipt["outcome"] == "granted"
        and granted_receipt["scope"] == "once",
    )

    def request_for(snapshot: dict, template: dict, artifact_id: str) -> dict:
        request = deepcopy(template)
        for field in ("workspace_id", "run_id", "task_id"):
            if snapshot[field] is None:
                request.pop(field, None)
            else:
                request[field] = snapshot[field]
        bound_hash = snapshot_digest(snapshot)
        request["payload"].update({
            "action": snapshot["action"], "bound_hash": bound_hash,
            "snapshot_ref": {"artifact_id": artifact_id, "version": 1, "checksum": bound_hash},
            "reason": "Reference fixture request for " + snapshot["action"],
        })
        return request

    def probe(name: str, accepted: bool, request: dict | None = None, **fields: Any) -> None:
        errors = approval_errors(request or requests["git.merge"], artifacts, schemas, registry, **fields)
        check(f"probe:approval_{name}", (not errors) == accepted, {"expected_accept": accepted, "errors": errors})

    for action, request in requests.items():
        probe("example_" + action, True, request)
    tool = fixtures["approval_tool"]
    tool_request = request_for(tool, requests["git.merge"], "art_01J9ZB6W9B4V3CGZKBZ01PDVKT")
    artifacts[("art_01J9ZB6W9B4V3CGZKBZ01PDVKT", 1)] = rfc8785.dumps(tool)
    probe("tool_snapshot", True, tool_request)
    probe("valid_grant", True, grant=grants[0], status="granted", now="2026-10-06T10:29:59Z")
    probe("expired_at_boundary", False, grant=grants[0], now="2026-10-06T10:30:00Z")
    for state in ("invalidated", "rejected", "expired"):
        probe("late_grant_" + state, False, grant=grants[0], status=state)
    probe("contract_stale", False, grant=grants[0], contract_current=False)
    probe("wrong_grant_hash", False, grant={**grants[0], "bound_hash": "sha256:" + "a" * 64})
    probe("wrong_grant_id", False, grant={**grants[0], "approval_id": "apr_01J9ZB6W9B4V3CGZKBZ01PDVKL"})
    probe("merge_budget_override", False, grant={**grants[0], "budget_override": {"max_cost_usd": 1.3}})
    budget_grant = {**grants[0], **{
        field: requests["budget.increase"]["payload"][field] for field in ("approval_id", "bound_hash")
    }}
    probe("budget_grant", True, requests["budget.increase"], grant=budget_grant)
    probe("budget_matching_override", True, requests["budget.increase"], grant={
        **budget_grant, "budget_override": {"max_cost_usd": 1.3},
    })
    probe("budget_changed_override", False, requests["budget.increase"], grant={
        **budget_grant, "budget_override": {"max_cost_usd": 2.0},
    })
    for field in ("workspace_id", "run_id", "task_id"):
        changed_request = deepcopy(requests["git.merge"])
        changed_request[field] = {"workspace_id": "ws_other", "run_id": "RUN-002", "task_id": "TASK-002"}[field]
        probe("wrong_" + field, False, changed_request)
    changed_request = deepcopy(requests["git.merge"])
    changed_request["payload"]["snapshot_ref"]["version"] = 2
    probe("snapshot_wrong_version", False, changed_request)
    changed_request = deepcopy(requests["git.merge"])
    changed_request["payload"]["snapshot_ref"]["checksum"] = "sha256:" + "a" * 64
    probe("snapshot_wrong_checksum", False, changed_request)
    changed_request["payload"]["bound_hash"] = "sha256:" + "a" * 64
    probe("prefixed_git_oid_is_not_snapshot_hash", False, changed_request)
    check("probe:approval_missing_artifact", bool(approval_errors(
        requests["git.merge"], {}, schemas, registry,
    )))
    for field in ("expected_base", "candidate_commit", "candidate_tree", "gate_recipe_hash"):
        changed = deepcopy(merge)
        changed["inputs"]["candidate"][field] = ("sha256:" if field == "gate_recipe_hash" else "") + "f" * (
            64 if field == "gate_recipe_hash" else 40
        )
        probe("changed_" + field, False, grant=grants[0], current_snapshot=changed)
    for field in ("policy_hash", "contract_hash"):
        probe("changed_" + field, False, grant=grants[0], current_snapshot={**merge, field: "sha256:" + "f" * 64})
    changed = deepcopy(merge)
    changed["inputs"]["candidate"]["expected_base"] = changed["inputs"]["candidate"]["candidate_commit"]
    probe("base_moved_before_cas", False, grant={**grants[0], "scope": "run"}, current_snapshot=changed)
    changed_tool = deepcopy(tool)
    changed_tool["inputs"]["arguments"]["label"] = "changed"
    probe("changed_tool_arguments", False, tool_request, current_snapshot=changed_tool)
    changed_tool = deepcopy(tool)
    changed_tool["inputs"]["resources"][0]["version"] = "sha256:" + "f" * 64
    probe("changed_resource_version", False, tool_request, current_snapshot=changed_tool)
    check("probe:approval_jcs_key_order", snapshot_digest(dict(reversed(list(merge.items())))) == snapshot_digest(merge))
    check("probe:approval_unicode_not_normalized", snapshot_digest({"label": "é"}) != snapshot_digest({"label": "e\u0301"}))
    check("probe:approval_utf8_vector", "界".encode() in artifacts[("art_01J9ZB6W9B4V3CGZKBZ01PDVKT", 1)])
    for resource_ids, accepted in (
        (["\U00010000", "\uffff"], True), (["\uffff", "\U00010000"], False), (["same", "same"], False),
    ):
        changed_tool = deepcopy(tool)
        changed_tool["inputs"]["resources"] = [
            {"resource_id": value, "version": str(index)} for index, value in enumerate(resource_ids)
        ]
        changed_request = request_for(changed_tool, tool_request, "art_01J9ZB6W9B4V3CGZKBZ01PDVKT")
        errors = approval_errors(changed_request, {
            ("art_01J9ZB6W9B4V3CGZKBZ01PDVKT", 1): rfc8785.dumps(changed_tool),
        }, schemas, registry)
        check(f"probe:approval_resource_order:{repr(resource_ids)}", (not errors) == accepted, errors)
    for value in (float("nan"), float("inf"), 2**64, "\ud800"):
        try:
            snapshot_digest({"invalid": value})
            rejected = False
        except (ValueError, TypeError, UnicodeError):
            rejected = True
        check(f"probe:approval_unsafe_value:{repr(value)}", rejected)
    for kind, result in (("gate", "fail"), ("review", "request_changes")):
        for mutation in ("result", "candidate", "contract_hash"):
            bad_evidence = deepcopy(fixtures["merge_" + kind])
            if mutation == "result":
                bad_evidence["result"] = result
            elif mutation == "candidate":
                bad_evidence["binding"]["candidate"]["candidate_commit"] = "f" * 40
            else:
                bad_evidence["binding"]["contract_hash"] = "sha256:" + "f" * 64
            changed = deepcopy(merge)
            reference = changed["inputs"][kind + "_evidence"]
            reference["checksum"] = snapshot_digest(bad_evidence)
            changed_request = request_for(changed, requests["git.merge"], "art_01J9ZB6W9B4V3CGZKBZ01PDVKR")
            changed_artifacts = {
                **artifacts,
                ("art_01J9ZB6W9B4V3CGZKBZ01PDVKR", 1): rfc8785.dumps(changed),
                (reference["artifact_id"], reference["version"]): rfc8785.dumps(bad_evidence),
            }
            errors = approval_errors(changed_request, changed_artifacts, schemas, registry)
            check(f"probe:approval_rehashed_{kind}_{mutation}", bool(errors), errors)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--baseline-ref", help="Git ref used to check preservation of existing numbered headings")
    args = parser.parse_args()
    report = audit(args.root, args.baseline_ref)
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], **report["counts"]}, indent=2))
    for entry in report["checks"]:
        if not entry["passed"]:
            print(f"FAIL {entry['name']}: {entry['detail']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
