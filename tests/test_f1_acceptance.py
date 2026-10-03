"""F1 integration gaps: real collaboration, saved evidence and report contracts.

All model responses are hand authored; no automatic test opens a network transport.
"""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from testgen_agent import models as m
from testgen_agent.agent import run_agent
from testgen_agent.config import load_config
from testgen_agent import f1_validation
from testgen_agent.llm_client import DeepSeekClient, RetryPolicy
from testgen_agent.tools import analyze_source, build_call_graph, candidate_entry_functions
from test_agent_loop import SequenceClient, task_request, candidate, POS, run
from test_generation import relationship_generated, single_function_generated
from test_llm_client import completion


WORKFLOW = '''def normalize(value):
    if value < 0:
        raise ValueError("negative")
    return value + 1

def summarize(value):
    return normalize(value) * 2
'''


def test_multilevel_calls_preserve_each_location_and_only_root_entry(tmp_path):
    path = tmp_path / "chain.py"
    path.write_text("def leaf(value):\n    return value + 1\n\ndef middle(value):\n    return leaf(value) * 2\n\ndef entry(value):\n    return middle(value)\n", encoding="utf-8")
    source = analyze_source(path)
    assert [(item.caller, item.callee) for item in source.direct_calls] == [
        ("middle", "leaf"), ("entry", "middle")]
    assert [(item.caller, item.line, item.expression) for item in source.call_sites] == [
        ("middle", 5, "leaf(value)"), ("entry", 8, "middle(value)")]
    assert build_call_graph(source) == {"leaf": (), "middle": ("leaf",), "entry": ("middle",)}
    assert candidate_entry_functions(source) == ("entry",)
    assert source.unresolved_calls == ()


def workflow_candidate(source):
    edge = source.direct_calls[0]
    relation = m.RelationshipAnalysis(
        relation_id="normalization-workflow", kind="direct_call", confidence="confirmed",
        involved_functions=("summarize", "normalize"),
        evidence=(m.RelationshipEvidence(kind="source", detail="entry uses normalized value",
                                         call_site_ids=(edge.call_site_id,)),),
    )
    scenarios = tuple(m.TestScenario(
        scenario_id=name, target_function="summarize", category=category,
        inputs=m.ScenarioInput(args=(value,)), expected_behavior=expected,
        expected_basis=m.ExpectedBasis(kind="specification", detail="normalize then multiply; propagate ValueError"),
        test_kind="collaboration", involved_functions=("summarize", "normalize"),
        relationship_ids=(relation.relation_id,),
    ) for name, value, category, expected in (
        ("normal", 1, "normal", "returns 4"), ("invalid", -1, "exception", "raises ValueError")))
    return m.GeneratedTests(plan=m.TestPlan(
        schema_version="1.1", target_functions=("normalize", "summarize"), oracle_mode="specification",
        entry_functions=("summarize",), relationships=(relation,), scenarios=scenarios,
        strategy=tuple(m.StrategyDecision(subject_kind="function", function_name=name,
            decision="not_selected", reason="specified behavior verified through real entry")
            for name in ("normalize", "summarize")) + (
            m.StrategyDecision(subject_kind="relationship", relationship_id=relation.relation_id,
                decision="collaboration_test", reason="verify data composition and exception propagation"),),
    ), code='''import pytest
from subject import summarize

def test_normal():
    assert summarize(1) == 4

def test_invalid():
    with pytest.raises(ValueError):
        summarize(-1)
''', mappings=tuple(m.TestCaseMapping(test_function=f"test_{item.scenario_id}",
                                     scenario_ids=(item.scenario_id,)) for item in scenarios))


@pytest.mark.parametrize("variant,expected_kind", [
    (WORKFLOW, "passed"),
    (WORKFLOW.replace("* 2", "* 3"), "assertion_failed"),
    (WORKFLOW.replace('raise ValueError("negative")', 'raise TypeError("negative")'), "execution_error"),
    (WORKFLOW.replace('raise ValueError("negative")', "return 0"), "assertion_failed"),
], ids=["correct", "broken-data-flow", "wrong-exception-type", "missing-exception"])
def test_real_entry_runs_dependency_and_observes_composition_and_exceptions(tmp_path, variant, expected_kind):
    path = tmp_path / "source.py"
    path.write_text(variant, encoding="utf-8")
    source = analyze_source(path)
    generated = workflow_candidate(source)
    client = SequenceClient([generated])
    request = m.TaskInput(source_path=path, output_dir=tmp_path / "run",
                          model=m.ModelInfo(model="offline-f1", base_url="https://example.com"))
    result = run_agent(request, client=client, oracle_mode=m.OracleMode.SPECIFICATION,
                       behavior_specification="summarize computes (value + 1) * 2; negative raises ValueError.")
    measured = result.state.history[0]
    assert measured.execution.kind == expected_kind
    assert measured.execution.collected == 2
    assert len(client.contexts) == 1
    assert path.read_text(encoding="utf-8") == variant
    checks, report = f1_validation.check_saved_run(result)
    assert all(checks.values())
    if expected_kind == "passed":
        assert result.decision.status == "completed"
        assert measured.coverage.line_percent == measured.coverage.branch_percent == 100
        # No test calls normalize directly, so these executed lines prove real dependency execution.
        assert not ({2, 3, 4} & set(measured.coverage.missing_lines))
        assert report.metrics.all_passed
    else:
        assert result.decision.action == "request_review"
        assert not report.metrics.all_passed
        assert measured.execution.failures
        assert (request.output_dir / measured.test_path).read_text(encoding="utf-8") == generated.code
        if expected_kind == "execution_error":
            assert result.final_test_file is None
        else:
            assert result.final_test_file.read_text(encoding="utf-8") == generated.code


def test_previous_passing_candidate_current_defect_and_report_preserve_distinct_facts(task_request):
    failed = candidate([POS, ("zero", 0, 99)])
    result, client = run(task_request, [candidate([POS]), failed],
                         behavior_specification="| 输入 | 预期 |\n|---|---|\n| 0 | 99 |")
    checks, report = f1_validation.check_saved_run(result)
    assert all(checks.values())
    assert result.state.stop_reason == "suspected_source_defect"
    assert report.status == "needs_review"
    assert report.selected_round == 1
    assert report.metrics.all_passed  # selected earlier test, not overall task completion
    assert report.rounds[1].execution.failed == 1
    assert report.unresolved_issues[0].round_number == 2
    assert report.metrics.line_percent == report.rounds[0].coverage.line_percent
    assert "== 99" in report.rounds[1].generated.code
    assert "test_zero" not in result.final_test_file.read_text(encoding="utf-8")
    assert len(client.contexts) == 2
    with pytest.raises(ValidationError):
        report.updated(status="completed", stop_reason="coverage_target_met")
    assert m.FinalReport.model_validate_json(report.canonical_json()) == report


@pytest.mark.parametrize("artifact", ["state.json", "summary.json", "test_subject.py", "trace.jsonl"])
def test_evidence_audit_detects_tampered_exports(task_request, artifact):
    result, _ = run(task_request.updated(max_rounds=1), [candidate([POS])])
    path = task_request.output_dir / artifact
    if artifact == "test_subject.py":
        path.write_text("# overwritten\n", encoding="utf-8")
    elif artifact == "trace.jsonl":
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["api_calls"] += 1
        path.write_text(json.dumps(data), encoding="utf-8")
    checks, _ = f1_validation.check_saved_run(result)
    assert not all(checks.values())


def test_f1_validation_can_be_exercised_entirely_offline(tmp_path):
    config = load_config(environ={"LLM_MODEL": "offline-f1", "DEEPSEEK_API_KEY": "fake-key"},
                         env_file=_empty_config(tmp_path))
    total = single_function_generated("calculate_total", code="from subject import calculate_total\ndef test_behavior():\n    assert calculate_total(12, 3) == 36\n")
    workflow = relationship_generated(analyze_source(Path(__file__).parents[1] / "examples/relationships.py"))
    record = f1_validation.validate(tmp_path / "outputs", config=config,
                                   client=SequenceClient([total, workflow]), execution_mode="offline-fixture")
    assert record["status"] == "passed"
    assert record["network_http_attempts"] == 0
    assert len(record["cases"]) == 2
    assert all(all(item["checks"].values()) for item in record["cases"])
    assert "fake-key" not in json.dumps(record)


def _empty_config(tmp_path):
    path = tmp_path / "empty.env"
    path.write_text("", encoding="utf-8")
    return path


def test_missing_key_is_reported_without_constructing_transport(tmp_path, monkeypatch):
    path = _empty_config(tmp_path)
    monkeypatch.setattr(f1_validation, "load_config", lambda: load_config(env_file=path, environ={"LLM_MODEL": "offline-f1"}))
    def forbidden(*args, **kwargs):
        pytest.fail("missing key must stop before client creation")
    monkeypatch.setattr(f1_validation, "DeepSeekClient", forbidden)
    record = f1_validation.validate(tmp_path / "outputs")
    assert record["status"] == "failed"
    assert record["error"]["code"] == "configuration"
    assert record["network_http_attempts"] == 0
    assert record["cases"] == []
    assert (Path(record["workspace"]) / "validation.json").is_file()


def test_real_adapter_transient_retry_then_complete_agent_is_counted(task_request, tmp_path):
    generated = candidate([POS, ("zero", 0, 0), ("negative", -1, -1)])
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(503, text="transient response body") if len(calls) == 1 else completion(
            generated.canonical_json(), model="offline-f1", usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12})
    config = load_config(env_file=_empty_config(tmp_path),
                         environ={"LLM_MODEL": "offline-f1", "DEEPSEEK_API_KEY": "transient-secret"})
    client = DeepSeekClient(config, transport=httpx.MockTransport(handle), sleep=lambda _: None,
                            retry_policy=RetryPolicy(max_transient_retries=1, max_format_repairs=0))
    result = run_agent(task_request.updated(model=m.ModelInfo(model="offline-f1", base_url=config.base_url)),
                       client=client, oracle_mode=m.OracleMode.SPECIFICATION)
    assert result.decision.status == "completed"
    assert len(calls) == result.state.api_calls == 2
    assert result.state.token_usage.total_tokens == 12
    assert all(f1_validation.check_saved_run(result)[0].values())
    logs = result.trace_file.read_text(encoding="utf-8") + result.metadata_file.read_text(encoding="utf-8")
    assert "transient-secret" not in logs
    assert "transient response body" not in logs


def test_live_cli_requires_explicit_flag(tmp_path):
    with pytest.raises(SystemExit) as error:
        f1_validation.main(["--output", str(tmp_path / "unused")])
    assert error.value.code == 2
    assert not (tmp_path / "unused").exists()
