# F1 自身测试与真实端到端验收

自动测试位于 `tests/`；模型生成的测试在运行工作区 `rounds/`，精选生成产物在 `evaluation/f1/`。自身测试的 coverage 配置只统计 `testgen_agent`，生成测试的工具 coverage 只统计该工作区 `subject.py`，两种结果分别记录。

```powershell
# 不调用 API；包含真实本地 pytest/coverage 子进程
.\.venv\Scripts\python.exe -m pytest -q -W error
# 需要现有 DeepSeek 配置；发送两项固定课程样例，可能产生费用
.\.venv\Scripts\python.exe -m testgen_agent.f1_validation --live
```

真实入口只发送 `examples/calculation.py/.md` 与 `examples/relationships.py/.md` 及正式 Prompt，不发送隐藏参考测试。每项最多 2 轮，每轮最多 1 次暂态重试、1 次格式修复，输出上限 4096 tokens；一轮成功时不再请求。每次创建独立 `outputs/f1/<UUID>/`，可用 `--output` 更换根目录。配置失败、模型错误和停止原因如实保存；退出码 0 表示两项验收全部通过，1 表示失败，缺少 `--live` 为参数错误 2。

验收检查真实任务状态、覆盖目标、协作场景与依赖执行、原文件不变、轮次预算、每轮快照、选中代码、结束摘要与轨迹，并按现有 `FinalReport` 契约保存 `report_contract.json`。这不是 G2 的 Markdown/JSON 报告展示实现。HTTP 尝试数来自适配器，连接失败不代表远端已收到请求；未知 token 用量保留 `null`。

| F1 要求 | 自动证据 |
|---|---|
| 中文、语法错误、无函数、不支持输入 | `test_source_analysis.py` |
| 独立、直接/多层调用、数据传递、遮蔽、递归、动态调用及位置 | `test_call_analysis.py`、`test_f1_acceptance.py` |
| 关系策略、场景和步骤引用 | `test_relationship_models.py`、`test_generation.py` |
| 真实依赖、组合结果及异常传播 | `test_f1_acceptance.py`，只调用入口的手写 mock 候选在正确/数据错误/异常类型错误/漏抛异常实现上执行 |
| JSON、字段、测试代码校验 | `test_llm_client.py`、`test_models.py`、`test_generation.py` |
| 通过、失败、无测试、导入错误、超时及覆盖范围 | `test_test_runner.py`、`test_coverage_runner.py`、`test_d3_validation.py` |
| 动作、记忆、上限与停止 | `test_agent.py`、`test_agent_loop.py`、`test_tracing.py` |
| 疑似源码缺陷保留断言 | `test_failure_analysis.py`、`test_agent_loop.py`、`test_f1_acceptance.py` |
| 历史/失败候选与报告契约、导出篡改检测 | `test_f1_acceptance.py`、`test_models.py` |
| Key 缺失、临时 API 错误、重试与计数 | `test_config.py`、`test_llm_client.py`、`test_f1_acceptance.py` |

2026-10-03 真实验收使用 `deepseek-flash`：Prompt `b3-v4` 两项响应将明确域外范围写成阻塞问题，均在执行前停止。修正为 `b3-v5` 后，两项各一轮完成，计算 6 条、协作 4 条测试全通过；目标行覆盖分别 2/2、4/4，分支均不适用。成功批次共 2 次 HTTP 尝试、11,311 tokens；修正前响应另用 11,563 tokens，网络不可达批次用量未知。失败记录没有计入成功数，也未因通过 mock 而宣称真实验收通过。

精选摘要与文件映射见 `evaluation/f1_validation.json`，原始源码/候选/计划、API 结构化返回、状态/报告契约/轨迹、pytest 与 coverage 原始产物在 `evaluation/f1/passed/`；修正前产物在 `evaluation/f1/pre_fix/`。不保存 Key、认证头、原始请求头或 coverage 二进制数据库。真实验收只覆盖这两个正确实现的单轮效果，不是多轮效果评测或缺陷检出率实验，F2–F4 仍待实施。

回归记录：初次全套 **439 项**以 `-W error` 通过；加入多层调用检查及最终修订后，F1/Prompt **35 项**以同参数通过（包含全部 **14 项**新增 F1 检查），当前合计 **440 项**。`compileall`、`pip check` 和 `git diff --check` 通过。最终真实运行审核见 `evaluation/f1/final_audit.json`，自动测试命令与结果见 `evaluation/f1_tests.json`。
