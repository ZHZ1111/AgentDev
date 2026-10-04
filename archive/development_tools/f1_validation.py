"""F1 opt-in live end-to-end acceptance; automatic tests inject an offline client."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
from time import perf_counter
from uuid import uuid4

from .agent import AgentRunResult, run_agent
from .config import ConfigError, load_config
from .llm_client import DeepSeekClient, RetryPolicy
from .models import AgentState, CandidateRound, FinalReport, ModelInfo, OracleMode, TaskInput
from .prompts import PROMPT_VERSION


def check_saved_run(result: AgentRunResult) -> tuple[dict[str, bool], FinalReport]:
    """Compare saved snapshots and the selected export with actual host observations.

    This checks the existing FinalReport contract, not G2's future report renderer.
    """
    state = result.state
    root = state.request.output_dir
    report = FinalReport(
        schema_version=state.schema_version, run_id=state.run_id, request=state.request,
        oracle_mode=state.oracle_mode, status=result.decision.status, stop_reason=state.stop_reason,
        source_info=state.source_info, rounds=state.history, selected_round=state.best_available_round,
        final_test_file=result.final_test_file, trace_file=result.trace_file,
        unresolved_issues=state.issues, api_calls=state.api_calls, token_usage=state.token_usage,
    )
    summary = json.loads(result.summary_file.read_text(encoding="utf-8"))
    events = [json.loads(line) for line in result.trace_file.read_text(encoding="utf-8").splitlines()]
    selected = state.history[state.best_available_round - 1] if state.best_available_round else None
    checks = {
        "state_snapshot_matches": AgentState.model_validate_json(result.state_file.read_text(encoding="utf-8")) == state,
        "candidate_snapshots_match": all(
            CandidateRound.model_validate_json((root / f"rounds/{item.number:02d}/candidate.json").read_text(encoding="utf-8")) == item
            for item in state.history
        ),
        "summary_matches": all(summary[name] == expected for name, expected in {
            "status": report.status, "stop_reason": report.stop_reason,
            "selected_round": report.selected_round, "api_calls": report.api_calls,
            "executed_rounds": report.metrics.executed_rounds,
            "final_test_file": str(report.final_test_file) if report.final_test_file else None,
            "token_usage": report.token_usage.model_dump(mode="json") if report.token_usage else None,
            "unresolved_issues": [item.model_dump(mode="json") for item in report.unresolved_issues],
        }.items()),
        "selected_test_matches": (
            result.final_test_file.read_text(encoding="utf-8") == selected.generated.code
            if selected else result.final_test_file is None
        ),
        "terminal_trace_matches": bool(events) and events[-1]["phase"] == "run_finished"
            and events[-1]["result_summary"]["status"] == report.status
            and events[-1]["result_summary"]["stop_reason"] == report.stop_reason
            and events[-1]["result_summary"]["selected_round"] == report.selected_round
            and events[-1]["result_summary"]["api_calls"] == report.api_calls,
        "round_budget_respected": len(state.history) <= state.request.max_rounds,
        "raw_execution_and_coverage_retained": all(
            any((directory / "stdout.txt").is_file() and (directory / "coverage.json").is_file()
                for directory in (root / f"rounds/{item.number:02d}/executions").glob("run-*"))
            for item in state.history if item.execution and item.coverage and item.coverage.status == "available"
        ),
    }
    return checks, report


def validate(output: Path, *, config=None, client=None, execution_mode: str = "live") -> dict:
    if execution_mode not in {"live", "offline-fixture"}:
        raise ValueError("execution_mode must identify live or offline-fixture provenance")
    if client is not None and config is None:
        raise ValueError("an injected client requires explicit public task configuration")
    root = (output / uuid4().hex).resolve()
    root.mkdir(parents=True, exist_ok=False)
    record = {
        "stage": "F1", "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(), "prompt_version": PROMPT_VERSION,
        "execution_mode": execution_mode, "workspace": str(root),
        "cases": [], "max_rounds_per_case": 2, "network_http_attempts": 0,
        "notes": "Fixed public examples only; no reference tests supplied to the model. G2 rendering remains pending.",
    }
    try:
        config = config or load_config()
    except ConfigError as error:
        record.update(status="failed", error={"code": "configuration", "message": str(error)})
    else:
        client = client or DeepSeekClient(config, retry_policy=RetryPolicy(
            max_transient_retries=1, max_format_repairs=1), max_tokens=4096)
        record["adapter_config"] = client.safe_config if isinstance(client, DeepSeekClient) else {
            "adapter_type": type(client).__name__}
        project = Path(__file__).resolve().parents[2]
        for name in ("calculation", "relationships"):
            source = project / f"examples/{name}.py"
            spec = project / f"examples/{name}.md"
            source_bytes, spec_bytes = source.read_bytes(), spec.read_bytes()
            request = TaskInput(
                source_path=source, spec_path=spec, output_dir=root / name,
                model=ModelInfo(provider=config.provider, model=config.model, base_url=config.base_url),
                max_rounds=2, execution_timeout_seconds=30,
            )
            started = perf_counter()
            result = run_agent(request, client=client, oracle_mode=OracleMode.SPECIFICATION)
            checks, report = check_saved_run(result)
            checks.update({
                "source_and_spec_unchanged": source.read_bytes() == source_bytes and spec.read_bytes() == spec_bytes,
                "completed_on_correct_implementation": report.status == "completed" and report.metrics.all_passed,
                "coverage_target_met": report.stop_reason == "coverage_target_met",
            })
            if name == "relationships":
                selected = result.state.history[result.state.best_available_round - 1] if result.state.best_available_round else None
                checks["collaboration_scenario_and_dependency_executed"] = bool(selected and selected.generated and
                    any(item.test_kind == "collaboration" and item.target_function == "checkout"
                        and set(item.involved_functions) == {"checkout", "calculate_total"}
                        for item in selected.generated.plan.scenarios) and selected.execution.all_passed
                    and selected.coverage and selected.coverage.status == "available"
                    and selected.coverage.line_percent == 100)
            case = {
                "case": name, "run_id": report.run_id, "workspace": str(request.output_dir),
                "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
                "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
                "duration_seconds": round(perf_counter() - started, 6),
                "status": report.status, "stop_reason": report.stop_reason,
                "metrics": report.metrics.model_dump(mode="json"),
                "token_usage": report.token_usage.model_dump(mode="json") if report.token_usage else None,
                "checks": checks, "passed": all(checks.values()),
                "model_responses": [
                    json.loads(path.read_text(encoding="utf-8"))["response_model"]
                    for path in sorted(request.output_dir.glob("rounds/*/llm_result.json"))
                ],
            }
            (request.output_dir / "report_contract.json").write_text(report.canonical_json(indent=2) + "\n", encoding="utf-8")
            record["cases"].append(case)
        record["network_http_attempts"] = sum(item["metrics"]["api_calls"] for item in record["cases"]) if execution_mode == "live" else 0
        record["status"] = "passed" if all(item["passed"] for item in record["cases"]) else "failed"
    (root / "validation.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="F1：两项固定课程样例的真实 API 端到端验收。")
    parser.add_argument("--live", action="store_true", required=True,
                        help="发送固定 examples/calculation 和 relationships 的源码/规格，可能产生 API 费用")
    parser.add_argument("--output", type=Path, default=Path("outputs/f1"))
    args = parser.parse_args(argv)
    result = validate(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
