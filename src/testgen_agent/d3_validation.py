"""Repeatable D3 acceptance against handwritten oracles and direct CLI runs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter
from uuid import uuid4
import xml.etree.ElementTree as ET

from .tools import run_tests_with_coverage


FIXTURES = Path(__file__).resolve().parents[2] / "validation/d3"
CASES = ("passed", "assertion_failed", "runtime_error", "import_failed", "empty", "timeout")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprints(directory: Path) -> dict[str, str]:
    return {path.relative_to(directory).as_posix(): _sha256(path) for path in sorted(directory.rglob("*")) if path.is_file()}


def _prepare(root: Path, candidate: str) -> Path:
    (root / "rounds/01").mkdir(parents=True, exist_ok=False)
    shutil.copyfile(FIXTURES / "source.py", root / "subject.py")
    shutil.copyfile(FIXTURES / f"{candidate}.py", root / "rounds/01/test_subject.py")
    return root


def _reference_environment(root: Path) -> dict[str, str]:
    # Independently constructed: no D1 helper or Agent recording plugin.
    essentials = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "TEMP", "TMP", "TMPDIR"}
    environment = {key: value for key, value in os.environ.items() if key.upper() in essentials}
    environment.update(
        PYTHONPATH=str(root), PYTHONIOENCODING="utf-8", PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
    )
    return environment


def _reference_process(command: list[str], root: Path, label: str, timeout: int) -> dict:
    diagnostics = root / "reference"
    _write_json(diagnostics / f"{label}.command.json", command)
    started = perf_counter()
    timed_out = False
    with (diagnostics / f"{label}.stdout.txt").open("wb") as stdout, (
        diagnostics / f"{label}.stderr.txt"
    ).open("wb") as stderr:
        process = subprocess.Popen(
            command, cwd=root, env=_reference_environment(root), shell=False,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
        )
        try:
            exit_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()  # The controlled reference fixture only sleeps; no descendants.
            exit_code = process.wait()
        except KeyboardInterrupt:
            process.kill()
            process.wait()
            raise
    return {"exit_code": exit_code, "timed_out": timed_out, "duration_seconds": perf_counter() - started}


def _junit(path: Path) -> dict | None:
    try:
        cases = list(ET.parse(path).getroot().iter("testcase"))
        result = {
            "reported_cases": len(cases),
            "failures": sum(case.find("failure") is not None for case in cases),
            "errors": sum(case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases),
        }
        result["passed"] = result["reported_cases"] - result["failures"] - result["errors"] - result["skipped"]
        return result
    except (OSError, ET.ParseError):
        return None


def _raw_coverage(path: Path) -> dict | None:
    """Independent JSON reader: do not call D2's parser or percentage helpers."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["meta"]["branch_coverage"] is not True or set(data["files"]) != {"subject.py"}:
            return None
        file = data["files"]["subject.py"]
        summary = file["summary"]
        return {
            "covered_lines": summary["covered_lines"], "total_lines": summary["num_statements"],
            "covered_branches": summary["covered_branches"], "total_branches": summary["num_branches"],
            "executed_lines": file["executed_lines"], "missing_lines": file["missing_lines"],
            "executed_branches": sorted(file["executed_branches"]), "missing_branches": sorted(file["missing_branches"]),
            "line_percent": 100 * summary["covered_lines"] / summary["num_statements"],
            "branch_percent": 100 * summary["covered_branches"] / summary["num_branches"],
        }
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError):
        return None


def _reference(root: Path, timeout: int) -> dict:
    artifacts = root / "reference"
    artifacts.mkdir()
    config = artifacts / "pytest.ini"
    config.write_text("[pytest]\naddopts =\n", encoding="utf-8")
    rcfile = artifacts / ".coveragerc"
    rcfile.write_text("[run]\nbranch = True\n[report]\nfail_under = 0\n", encoding="utf-8")
    command = [
        sys.executable, "-P", "-m", "coverage", "run", f"--rcfile={rcfile}",
        f"--data-file={artifacts / '.coverage'}", "--branch", "-m", "pytest",
        "-c", str(config), "--rootdir", str(root), "--noconftest", "--import-mode=importlib",
        "-p", "no:cacheprovider", f"--junitxml={artifacts / 'pytest.xml'}",
        "--color=no", "--tb=short", "-q", "rounds/01/test_subject.py",
    ]
    result = _reference_process(command, root, "pytest", timeout)
    result["junit"] = _junit(artifacts / "pytest.xml")
    result["coverage"] = None
    if not result["timed_out"]:
        export = _reference_process([
            sys.executable, "-P", "-m", "coverage", "json", f"--rcfile={rcfile}",
            f"--data-file={artifacts / '.coverage'}", "-o", str(artifacts / "coverage.json"),
            str(root / "subject.py"),
        ], root, "coverage_export", 30)
        result["export"] = export
        if export["exit_code"] == 0 and not export["timed_out"]:
            result["coverage"] = _raw_coverage(artifacts / "coverage.json")
    _write_json(artifacts / "observation.json", result)
    return result


def _pid_stopped(marker: Path) -> bool:
    try:
        pid = int(marker.read_text(encoding="utf-8"))
        if pid <= 0:
            return False
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
            kernel.WaitForSingleObject.restype = wintypes.DWORD
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel.CloseHandle.restype = wintypes.BOOL
            # SYNCHRONIZE only; no process enumeration, write or termination right.
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if not handle:
                return ctypes.get_last_error() == 87  # PID no longer exists.
            try:
                return kernel.WaitForSingleObject(handle, 0) == 0  # Signaled = terminated.
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def _validate_case(run_root: Path, name: str, expected: dict, oracles: dict, timeout: int) -> dict:
    tool_root = _prepare(run_root / name / "tool", name)
    reference_root = _prepare(run_root / name / "direct", name)
    test_hash = _sha256(FIXTURES / f"{name}.py")
    source_hash = _sha256(FIXTURES / "source.py")
    result = run_tests_with_coverage(tool_root, timeout=timeout if name == "timeout" else 30)
    reference = _reference(reference_root, timeout if name == "timeout" else 30)
    execution = result.execution
    counts = {key: getattr(execution, key) for key in expected["counts"]}
    checks = {
        "classification": execution.kind.value == expected["kind"],
        "counts": counts == expected["counts"],
        "all_passed": result.candidate_all_passed == expected["all_passed"],
        "source_copies_unchanged": all(_sha256(root / "subject.py") == source_hash for root in (tool_root, reference_root)),
        "test_copies_unchanged": all(_sha256(root / "rounds/01/test_subject.py") == test_hash for root in (tool_root, reference_root)),
        "diagnostics_retained": all((result.artifacts / filename).is_file() for filename in (
            "execution.json", "pytest_result.json", "stdout.txt", "stderr.txt", "run_result.json", "coverage_result.json",
        )) and all((reference_root / "reference" / filename).is_file() for filename in (
            "observation.json", "pytest.stdout.txt", "pytest.stderr.txt", "pytest.command.json",
        )),
    }
    if name == "timeout":
        checks.update(
            timed_out=execution.timed_out and reference["timed_out"],
            bounded_duration=execution.duration_seconds < timeout + 7 and reference["duration_seconds"] < timeout + 7,
            processes_stopped=_pid_stopped(tool_root / "timeout.pid") and _pid_stopped(reference_root / "timeout.pid"),
            incomplete_coverage_unavailable=result.coverage.status == "unavailable" and reference["coverage"] is None,
        )
    else:
        oracle = oracles[expected["coverage_oracle"]]
        tool_metrics = result.coverage.model_dump(mode="json")
        raw_tool = _raw_coverage(result.artifacts / "coverage.json")
        checks.update(
            exit_codes=execution.exit_code == reference["exit_code"] == expected["exit_code"],
            junit=reference["junit"] == expected["junit"] and _junit(result.artifacts / "pytest.xml") == expected["junit"],
            tool_raw_coverage=raw_tool == oracle,
            direct_raw_coverage=reference["coverage"] == oracle,
            tool_metrics=result.coverage.status == "available" and all(tool_metrics[key] == oracle[key] for key in (
                "covered_lines", "total_lines", "covered_branches", "total_branches", "missing_lines", "line_percent", "branch_percent",
            )) and [[arc.start, arc.end] for arc in result.coverage.missing_branches] == oracle["missing_branches"],
        )
        if "diagnostic" in expected:
            checks["failure_detail_retained"] = expected["diagnostic"] in execution.stdout + execution.stderr
    observation = {
        "name": name, "expected": expected, "checks": checks, "passed": all(checks.values()),
        "tool_execution": {"kind": execution.kind.value, "exit_code": execution.exit_code,
                           "counts": counts, "all_passed": execution.all_passed, "timed_out": execution.timed_out,
                           "duration_seconds": execution.duration_seconds},
        "tool_coverage": result.coverage.model_dump(mode="json"),
        "direct_reference": reference,
        "tool_artifacts": result.artifacts.relative_to(run_root).as_posix(),
        "reference_artifacts": (reference_root / "reference").relative_to(run_root).as_posix(),
    }
    # Use a portable target label in the summary; raw records keep their real path.
    observation["tool_coverage"]["target_file"] = "subject.py"
    _write_json(run_root / name / "comparison.json", observation)
    return observation


def _validate_sequence(run_root: Path, oracles: dict) -> dict:
    root = _prepare(run_root / "sequence", "passed")
    before = _sha256(root / "subject.py")
    records = []
    checks = {}
    retained = []
    for name, oracle_name in (("passed", "full"), ("positive_only", "positive"), ("negative_only", "negative")):
        shutil.copyfile(FIXTURES / f"{name}.py", root / "rounds/01/test_subject.py")
        result = run_tests_with_coverage(root)
        checks[f"{name}_metrics"] = result.candidate_all_passed and _raw_coverage(result.artifacts / "coverage.json") == oracles[oracle_name]
        checks[f"{name}_prior_artifacts_retained"] = all(_fingerprints(path) == fingerprints for path, fingerprints in retained)
        retained.append((result.artifacts, _fingerprints(result.artifacts)))
        records.append({"candidate": name, "artifacts": result.artifacts.relative_to(run_root).as_posix(),
                        "line_percent": result.coverage.line_percent, "branch_percent": result.coverage.branch_percent,
                        "missing_lines": list(result.coverage.missing_lines),
                        "missing_branches": [[arc.start, arc.end] for arc in result.coverage.missing_branches]})
        if name == "passed":
            shutil.copyfile(result.artifacts / ".coverage", root / ".coverage")
            old_hash = _sha256(root / ".coverage")
    checks["old_database_untouched"] = _sha256(root / ".coverage") == old_hash
    checks["distinct_execution_directories"] = len({record["artifacts"] for record in records}) == 3
    checks["source_copy_unchanged"] = _sha256(root / "subject.py") == before
    return {"runs": records, "checks": checks, "passed": all(checks.values())}


def validate_tools(output_root: str | Path = "outputs/d3", *, timeout: int = 3) -> dict:
    """Validate the fixed D3 suite; return and save real observations, even on mismatch."""
    if type(timeout) is not int or not 1 <= timeout <= 10:
        raise ValueError("D3 timeout must be an integer in 1..10 seconds")
    expectations = json.loads((FIXTURES / "expectations.json").read_text(encoding="utf-8"))
    if set(expectations["cases"]) != set(CASES):
        raise ValueError("D3 requires exactly its six handwritten acceptance cases")
    originals_before = _fingerprints(FIXTURES)
    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_root = (Path(output_root) / run_id).resolve()
    run_root.mkdir(parents=True, exist_ok=False)
    cases = [_validate_case(run_root, name, expectations["cases"][name], expectations["coverage_oracles"], timeout) for name in CASES]
    sequence = _validate_sequence(run_root, expectations["coverage_oracles"])
    originals_unchanged = originals_before == _fingerprints(FIXTURES)
    report = {
        "stage": "D3", "run_id": run_id, "tested_at_utc": started.isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "versions": {package: version(package) for package in ("pytest", "coverage")},
        "fixture_origin": expectations["origin"], "junit_interpretation": expectations["junit_interpretation"],
        "original_fingerprints": originals_before, "originals_unchanged": originals_unchanged,
        "cases": cases, "sequence": sequence, "artifact_root": str(run_root),
        "d3_passed": originals_unchanged and all(case["passed"] for case in cases) and sequence["passed"],
    }
    _write_json(run_root / "validation.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="D3：手写样例、原生命令与 D1/D2 工具的独立可信度验收。")
    parser.add_argument("--output", type=Path, default=Path("outputs/d3"))
    parser.add_argument("--timeout", type=int, default=3, help="受控超时样例时限，1..10 秒")
    parser.add_argument("--evidence", type=Path, help="另存精选 JSON；目标须不存在，防止覆盖旧证据")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 10:
        parser.error("--timeout must be in 1..10 seconds")
    if args.evidence is not None and args.evidence.exists():
        parser.error("evidence file already exists; choose a new path")
    report = validate_tools(args.output, timeout=args.timeout)
    if args.evidence is not None:
        with args.evidence.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    for case in report["cases"]:
        failed_checks = [name for name, passed in case["checks"].items() if not passed]
        print(f"{case['name']}: {'PASS' if case['passed'] else 'FAIL'} {failed_checks}")
    print(f"sequence: {'PASS' if report['sequence']['passed'] else 'FAIL'}")
    print(f"D3 passed: {report['d3_passed']}; artifacts: {report['artifact_root']}")
    return 0 if report["d3_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
