"""A3 environment verification, separate from the future generation controller."""

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
from typing import Any
from uuid import uuid4
import xml.etree.ElementTree as ET

import httpx

from .config import AppConfig, ConfigError, load_config
from .llm_client import create_http_client


def verify_llm(
    config: AppConfig, *, transport: httpx.BaseTransport | None = None,
) -> dict[str, Any]:
    """Send one short request; no retries, source upload or test generation."""
    result: dict[str, Any] = {
        "status": "failed", "provider": config.provider, "model": config.model,
        "base_url": config.base_url, "attempts": 1,
        "latency_limit_seconds": 30, "max_tokens": 16,
    }
    start = perf_counter()
    try:
        with create_http_client(config, transport=transport) as client:
            response = client.post("chat/completions", json={
                "model": config.model,
                "messages": [{"role": "user", "content": "Reply with exactly OK and nothing else."}],
                "stream": False,
                "max_tokens": 16,
                "thinking": {"type": "disabled"},
            })
        result["latency_seconds"] = round(perf_counter() - start, 3)
        result["http_status"] = response.status_code
        if response.status_code != 200:
            result["error"] = {
                400: "请求参数或模型无效，请检查模型配置。",
                401: "认证失败，请检查本地 Key。",
                402: "账号余额不足。",
                403: "账号无访问权限。",
                429: "服务限流；本验证不会自动重试。",
            }.get(response.status_code, "服务返回非成功状态；未记录响应正文。")
            return result
        data = response.json()
        choice = data["choices"][0]
        content = choice["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty response")
        result["response_model"] = data.get("model")
        result["finish_reason"] = choice.get("finish_reason")
        # Only the expected fixed answer is recorded, not arbitrary server text.
        result["answer_matches_expected"] = content.strip() == "OK"
        if result["answer_matches_expected"]:
            result["answer"] = "OK"
        usage = data.get("usage")
        result["usage"] = {
            key: usage[key] for key in (
                "prompt_tokens", "completion_tokens", "total_tokens",
                "prompt_cache_hit_tokens", "prompt_cache_miss_tokens",
            ) if isinstance(usage, dict) and type(usage.get(key)) is int
        } or None
        if (
            result["answer_matches_expected"] and result["finish_reason"] == "stop"
            and result["latency_seconds"] <= result["latency_limit_seconds"]
        ):
            result["status"] = "passed"
        else:
            result["error"] = "响应内容、结束原因或时长未达到本次验证条件。"
    except httpx.HTTPError as error:
        result["latency_seconds"] = round(perf_counter() - start, 3)
        result["error_type"] = type(error).__name__
        result["error"] = "请求超时或网络连接失败；未记录请求头、密钥或异常原文。"
    except (ValueError, KeyError, IndexError, TypeError):
        result["error"] = "服务响应缺少可用的对话结果；未记录原始响应正文。"
    return result


def _test_environment() -> dict[str, str]:
    # Preserve only OS/process essentials, so API credentials never reach pytest.
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "USERPROFILE", "APPDATA", "LOCALAPPDATA", "LD_LIBRARY_PATH",
    }
    environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    environment.update(PYTHONIOENCODING="utf-8", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    return environment


def verify_test_environment(root: Path, workspace: Path, timeout: int) -> dict[str, Any]:
    """Run the fixed handwritten sample, with isolated pytest/coverage config."""
    source = root / "examples" / "calculation.py"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    shutil.copyfile(source, workspace / "subject.py")
    shutil.copyfile(
        root / "validation" / "handwritten" / "test_calculation.py",
        workspace / "test_subject.py",
    )
    (workspace / "pytest.ini").write_text("[pytest]\naddopts =\n", encoding="utf-8")
    (workspace / ".coveragerc").write_text("[run]\nbranch = True\n", encoding="utf-8")
    result: dict[str, Any] = {"status": "failed", "source_sha256": before}
    environment = _test_environment()
    commands = [
        [sys.executable, "-m", "coverage", "run", "--rcfile=.coveragerc", "--branch",
         f"--include={workspace / 'subject.py'}", "-m", "pytest", "-c", "pytest.ini",
         "test_subject.py", "--junitxml=pytest.xml", "-q"],
        [sys.executable, "-m", "coverage", "json", "--rcfile=.coveragerc",
         f"--include={workspace / 'subject.py'}", "-o", "coverage.json"],
    ]
    try:
        for label, command in zip(("pytest", "coverage_export"), commands):
            process = subprocess.run(
                command, cwd=workspace, env=environment, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=timeout,
            )
            (workspace / f"{label}.stdout.txt").write_text(process.stdout, encoding="utf-8")
            (workspace / f"{label}.stderr.txt").write_text(process.stderr, encoding="utf-8")
            result[f"{label}_exit_code"] = process.returncode
        cases = list(ET.parse(workspace / "pytest.xml").getroot().iter("testcase"))
        counts = {
            "tests": len(cases),
            "failures": sum(case.find("failure") is not None for case in cases),
            "errors": sum(case.find("error") is not None for case in cases),
            "skipped": sum(case.find("skipped") is not None for case in cases),
        }
        counts["passed"] = counts["tests"] - sum(counts[key] for key in ("failures", "errors", "skipped"))
        result["execution"] = counts
        coverage = json.loads((workspace / "coverage.json").read_text(encoding="utf-8"))
        files = coverage["files"]
        if len(files) != 1 or Path(next(iter(files))).name != "subject.py":
            raise ValueError("unexpected coverage scope")
        target = next(iter(files.values()))
        summary = target["summary"]
        result["coverage"] = {
            "target": "subject.py", "covered_lines": summary["covered_lines"],
            "total_lines": summary["num_statements"],
            "line_percent": 100 * summary["covered_lines"] / summary["num_statements"] if summary["num_statements"] else None,
            "covered_branches": summary["covered_branches"],
            "total_branches": summary["num_branches"],
            "branch_percent": 100 * summary["covered_branches"] / summary["num_branches"] if summary["num_branches"] else None,
            "missing_lines": target["missing_lines"],
            "missing_branches": target.get("missing_branches", []),
        }
        result["source_unchanged"] = hashlib.sha256(source.read_bytes()).hexdigest() == before
        if (
            result["pytest_exit_code"] == result["coverage_export_exit_code"] == 0
            and counts["tests"] == counts["passed"] == 3
            and result["coverage"]["line_percent"] == 100 and result["source_unchanged"]
        ):
            result["status"] = "passed"
    except subprocess.TimeoutExpired:
        result["error"] = "样例测试或覆盖率导出超时。"
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError):
        result["error"] = "无法取得正确的样例执行/覆盖结果，请查看运行目录中的工具日志。"
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if callable(getattr(stream, "reconfigure", None)) and not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="A3：真实 DeepSeek 最小请求及手写 pytest/coverage 环境验证。")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--model", help="覆盖本地模型配置；不提供时读取正常配置")
    parser.add_argument("--skip-llm", action="store_true", help="只验证本地测试环境，不调用 API")
    parser.add_argument("--output", type=Path, default=Path("outputs/a3"))
    parser.add_argument("--timeout", type=int, default=30, help="测试或覆盖导出单次超时，1..300 秒")
    args = parser.parse_args(argv)
    if not 1 <= args.timeout <= 300:
        parser.error("--timeout 必须是 1..300 的整数")
    root = Path(__file__).resolve().parents[2]
    timestamp = datetime.now(timezone.utc)
    run_id = timestamp.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    workspace = (args.output / run_id).resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "stage": "A3", "run_id": run_id, "tested_at_utc": timestamp.isoformat(),
        "python": platform.python_version(), "platform": platform.platform(),
        "versions": {name: version(name) for name in ("httpx", "pydantic", "pytest", "coverage")},
        "tests": verify_test_environment(root, workspace, args.timeout),
    }
    if args.skip_llm:
        result["llm"] = {"status": "skipped", "reason": "显式选择只验证本地测试环境。"}
    else:
        try:
            config = load_config(env_file=args.env_file, overrides={"model": args.model})
            result["llm"] = verify_llm(config)
        except ConfigError as error:
            result["llm"] = {"status": "failed", "error": str(error)}
    result["a3_passed"] = result["tests"]["status"] == result["llm"]["status"] == "passed"
    (workspace / "validation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"实测产物：{workspace}")
    return 0 if result["tests"]["status"] == "passed" and (args.skip_llm or result["a3_passed"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
