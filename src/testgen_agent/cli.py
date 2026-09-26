"""A2 CLI: inspect configuration locally; generation is not implemented yet."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from collections.abc import Sequence

from . import __version__
from .config import ConfigError, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="testgen-agent",
        description="测试生成 Agent（A2）：当前提供本地配置检查，尚未实现测试生成。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--check-config", action="store_true", help="校验并显示脱敏配置；不发送 API 请求")
    parser.add_argument("--env-file", type=Path, help="指定 UTF-8 .env 文件；默认只读取当前目录的 .env")
    parser.add_argument("--provider", help="LLM 服务商，当前支持 deepseek")
    parser.add_argument("--model", help="实际可用的 DeepSeek 模型标识")
    parser.add_argument("--base-url", help="DeepSeek 服务地址")
    parser.add_argument("--api-key-env", help="保存 API Key 的环境变量名；不接受命令行明文 Key")
    parser.add_argument("--request-timeout", type=int, dest="request_timeout_seconds", help="单次模型请求超时，1..600 秒")
    parser.add_argument("--max-rounds", type=int, help="候选执行轮数，1..3（含首轮）")
    parser.add_argument("--timeout", type=int, dest="execution_timeout_seconds", help="单轮测试执行超时，1..300 秒")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # Windows pipes otherwise default to the system code page. Emit UTF-8 so
    # redirected help/errors and CLI output use the same encoding as our files.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure) and not stream.isatty():
            reconfigure(encoding="utf-8")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.check_config:
        parser.error("当前阶段请使用 --check-config 或 --help；测试生成将在后续阶段实现。")
    overrides = {
        field: getattr(args, field)
        for field in (
            "provider", "model", "base_url", "api_key_env", "request_timeout_seconds",
            "max_rounds", "execution_timeout_seconds",
        )
    }
    try:
        config = load_config(env_file=args.env_file, overrides=overrides)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(config.safe_summary(), ensure_ascii=False, indent=2))
    print("配置检查通过（仅本地校验；此命令不验证模型权限、余额或网络可用性）。")
    return 0
