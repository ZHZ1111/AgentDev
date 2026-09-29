"""D3 acceptance: independent direct commands and immutable handwritten oracles."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from testgen_agent.d3_validation import FIXTURES, _pid_stopped, main, validate_tools


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    return validate_tools(tmp_path_factory.mktemp("d3-acceptance"))


def test_entire_acceptance_matches_handwritten_oracles(evidence):
    assert evidence["d3_passed"]
    assert len(evidence["cases"]) == 6
    assert evidence["originals_unchanged"] and evidence["sequence"]["passed"]


@pytest.mark.parametrize("name,kind,exit_code,all_passed", [
    ("passed", "passed", 0, True),
    ("assertion_failed", "assertion_failed", 1, False),
    ("runtime_error", "execution_error", 1, False),
    ("import_failed", "collection_error", 2, False),
    ("empty", "no_tests", 5, False),
    ("timeout", "timeout", None, False),
])
def test_classifications_agree_with_independent_reference(evidence, name, kind, exit_code, all_passed):
    case = next(case for case in evidence["cases"] if case["name"] == name)
    assert case["passed"]
    assert case["tool_execution"]["kind"] == kind
    assert case["tool_execution"]["all_passed"] is all_passed
    if exit_code is not None:
        assert case["direct_reference"]["exit_code"] == case["tool_execution"]["exit_code"] == exit_code
    else:
        assert case["direct_reference"]["timed_out"] and case["checks"]["processes_stopped"]


def test_junit_diagnostics_are_not_mistaken_for_test_item_counters(evidence):
    cases = {case["name"]: case for case in evidence["cases"]}
    assert cases["import_failed"]["direct_reference"]["junit"]["reported_cases"] == 1
    assert cases["import_failed"]["tool_execution"]["counts"]["collected"] == 0
    assert cases["runtime_error"]["direct_reference"]["junit"]["failures"] == 1
    assert cases["runtime_error"]["tool_execution"]["counts"]["errors"] == 1


def test_two_branch_oracle_uses_exact_lines_arcs_and_separate_denominators(evidence):
    case = next(case for case in evidence["cases"] if case["name"] == "assertion_failed")
    coverage = case["direct_reference"]["coverage"]
    assert (coverage["covered_lines"], coverage["total_lines"]) == (3, 4)
    assert (coverage["covered_branches"], coverage["total_branches"]) == (1, 2)
    assert coverage["executed_lines"] == [1, 2, 3]
    assert coverage["missing_lines"] == [4]
    assert coverage["executed_branches"] == [[2, 3]] and coverage["missing_branches"] == [[2, 4]]
    assert case["tool_coverage"]["line_percent"] == 75 and case["tool_coverage"]["branch_percent"] == 50


def test_timeout_records_a_started_call_even_without_its_completion_report(evidence):
    case = next(case for case in evidence["cases"] if case["name"] == "timeout")
    assert case["tool_execution"]["counts"]["executed"] == 1
    assert case["tool_execution"]["counts"]["passed"] == 0
    root = Path(evidence["artifact_root"])
    raw = json.loads((root / case["tool_artifacts"] / "pytest_result.json").read_text(encoding="utf-8"))
    assert len(raw["started_calls"]) == 1 and not raw["completed"]
    assert not any(report["when"] == "call" for report in raw["reports"])
    assert case["tool_coverage"]["status"] == "unavailable"


def test_sequence_keeps_previous_artifacts_and_does_not_merge_full_coverage(evidence):
    sequence = evidence["sequence"]
    assert all(sequence["checks"].values())
    assert [run["line_percent"] for run in sequence["runs"]] == [100, 75, 75]
    assert [run["branch_percent"] for run in sequence["runs"]] == [100, 50, 50]
    assert [run["missing_lines"] for run in sequence["runs"]] == [[], [4], [3]]
    assert len({run["artifacts"] for run in sequence["runs"]}) == 3


def test_reference_does_not_load_agent_result_plugin_and_failure_logs_survive(evidence):
    root = Path(evidence["artifact_root"])
    for case in evidence["cases"]:
        artifacts = root / case["reference_artifacts"]
        command = json.loads((artifacts / "pytest.command.json").read_text(encoding="utf-8"))
        assert "testgen_agent.tools._pytest_results" not in command
        assert command[-1] == "rounds/01/test_subject.py"
        assert case["checks"]["diagnostics_retained"]
        if "diagnostic" in case["expected"]:
            result = json.loads((root / case["tool_artifacts"] / "execution.json").read_text(encoding="utf-8"))
            assert case["expected"]["diagnostic"] in result["stdout"] + result["stderr"]


def test_original_fixture_bytes_stay_unchanged_and_report_round_trips(evidence):
    for filename, fingerprint in evidence["original_fingerprints"].items():
        assert hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest() == fingerprint
    saved = json.loads((Path(evidence["artifact_root"]) / "validation.json").read_text(encoding="utf-8"))
    assert saved == evidence


def test_process_guard_does_not_call_a_live_process_stopped(tmp_path):
    marker = tmp_path / "current.pid"
    marker.write_text(str(os.getpid()), encoding="utf-8")
    assert not _pid_stopped(marker)
    assert not _pid_stopped(tmp_path / "missing.pid")


def test_cli_refuses_to_overwrite_evidence_before_running(tmp_path):
    path = tmp_path / "existing.json"
    path.write_text("existing evidence", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        main(["--evidence", str(path), "--output", str(tmp_path / "not-created")])
    assert error.value.code == 2
    assert path.read_text(encoding="utf-8") == "existing evidence"
    assert not (tmp_path / "not-created").exists()
