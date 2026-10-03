# 测试生成 Agent

课程项目：为单个 Python 文件中的 1–5 个顶层同步纯函数生成并执行 pytest 测试集。设计目标是由 Agent 自动分析函数关系，决定单元测试和协作测试策略，再根据失败及覆盖率反馈进行有限迭代。LLM 服务商选用 DeepSeek。

当前完成 A1/A2/A3/B1/B2/C1/C1a、C2 的离线实现，以及 D1/D2 正式执行与覆盖工具、D3 独立可信度验收、E1–E4 控制器/失败分类/任务记忆/反馈循环/逐步轨迹、F1 自身测试与 F2 小型评测集。F1 将 Prompt 修订为 `b3-v5`，两项固定样例已完成真实 API 生成、校验、执行与覆盖验收。`run_agent()` 支持最多三轮候选，依据真实反馈继续或停止，保留旧测试、选择最佳候选并导出结束摘要和轨迹。真实 LLM 多轮效果尚未评测，CLI 和完整报告仍待后续阶段。设计与验收记录见 [Design.md](Design.md)，进度见 [TASK_CHECKLIST.md](TASK_CHECKLIST.md)。

2026-09-27 新增范围：自动判断同文件函数关系，并自主规划测试集。所需关系契约、Prompt、AST 结构与调用证据均已实现；首轮生成/执行可通过 E1 Python 接口连接，完整多轮 CLI 与报告仍未实现。修订任务预算为 58 小时。

## 函数关系与测试集

用户只需提供源码和必要的行为说明，无需手动列出函数关系或指定测试类型。AST 工具会保存调用点、确认边和未知调用，构造确认调用图、递归组件和候选入口；宿主再校验 Agent 给出的关系、入口及测试策略。图根只是候选，不能取代规格中的业务入口判断。

| 输入中的关系 | Agent 的预期处理 |
|---|---|
| 函数彼此独立 | 分别生成单元场景，不强行构造组合工作流 |
| 同文件内明确直接调用 | 分析入口和依赖，按需生成入口协作测试，同时考虑内部函数边界 |
| 有明确证据的数据传递 | 预期行为清楚时生成数据衔接测试，并记录依据 |
| 动态调用或共享可变状态 | 标记不确定性或范围限制；初版不承诺复杂动态分析和状态顺序测试 |

例如 `checkout` 调用 `validate_order` 和 `calculate_total`，Agent 可以为校验、计价分别生成单元测试，再调用真实 `checkout` 验证合法订单总价和规格规定的异常传播。同文件依赖默认真实执行，不用 mock 替换它们来制造通过结果。

存在调用关系不意味着必须追加重复测试。Agent 应记录为什么增加或不增加协作场景，报告说明入口、涉及函数、关系证据和预期依据。范围仍是单文件简单纯函数，不扩大为跨文件项目级测试。

## 安装（Windows PowerShell）

已验证环境：Windows x64、Python 3.13.9；项目暂限定 Python 3.13 系列。虚拟环境不随源码提交，首次安装需要访问 Python 包索引。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-index --no-build-isolation --no-deps -e .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m testgen_agent --help
```

直接使用虚拟环境解释器，无需激活环境或修改 PowerShell 执行策略。`requirements.lock` 固定了本次环境的直接、传递和构建依赖；`pyproject.toml` 声明项目及入口。锁文件基于 Windows / Python 3.13 验证，暂未验证其他平台。

## 配置 DeepSeek

```powershell
Copy-Item .env.example .env
```

编辑本地 `.env`，将 `LLM_MODEL` 替换为账号实际可用模型，将 `DEEPSEEK_API_KEY` 替换为自己的 Key。本项目已在 2026-09-26 实际验证 `deepseek-flash`，使用者仍需具备自己账号的权限。复制命令只用于首次配置，不要覆盖已有 `.env`。示例中的模型和 Key 占位符会被配置校验拒绝。

DeepSeek 官方示例使用服务地址 `https://api.deepseek.com`、Bearer 认证及 `POST /chat/completions`；模型标识以账号权限及当时官方文档为准。目前官方示例列出 `deepseek-flash` 和 `deepseek-v4-pro`，项目不自动选择模型，也不把本地校验当作模型权限验证。[首次调用 API](https://api-docs.deepseek.com/zh-cn/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)

| 环境变量 | 默认 / 约束 |
|---|---|
| `LLM_PROVIDER` | `deepseek`；当前仅支持此服务商 |
| `LLM_MODEL` | 必填，无默认值，不接受占位符 |
| `LLM_BASE_URL` | `https://api.deepseek.com`；支持保留 `/v1` 路径前缀 |
| `LLM_API_KEY_ENV` | `DEEPSEEK_API_KEY`；指定存放 Key 的环境变量名 |
| `DEEPSEEK_API_KEY` | 必填，无默认值；使用其他变量名时设置 `LLM_API_KEY_ENV` |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60`；1..600 秒，单次模型请求超时 |
| `AGENT_MAX_ROUNDS` | `3`；1..3，含首轮候选 |
| `TEST_EXECUTION_TIMEOUT_SECONDS` | `30`；1..300 秒，单轮测试执行超时 |

读取优先级为：命令行覆盖参数 > 进程环境变量 > 指定 `.env` 文件 > 默认值。默认只读取启动目录的 `.env`，不向父目录搜索；`--env-file` 可显式选择其他文件，不存在时立即报错。支持 UTF-8（含 BOM）；不展开 `${...}`，也不修改进程环境变量。

## 当前可运行命令

```powershell
.\.venv\Scripts\python.exe -m testgen_agent --check-config
.\.venv\Scripts\python.exe -m testgen_agent --check-config --max-rounds 1 --timeout 20
.\.venv\Scripts\testgen-agent.exe --version
.\.venv\Scripts\python.exe -m pytest
```

`--check-config` 只做本地校验，输出非敏感配置以及 `api_key_configured` 标记，不发送请求，也不生成测试或运行报告。退出码 0 表示本地校验成功；2 表示参数或配置无效。该命令不检查网络、余额或模型权限；实际连通性可通过下述 A3 入口验证。

缺少 Key、未替换占位符、非法 URL、非整数或超出范围的轮次/超时都会报配置错误；错误提示不包含被拒绝的配置值。不要通过命令行传入明文 Key。`.env`、虚拟环境、缓存及 `outputs/` 已加入忽略规则。

当前没有 `--source` / `--spec` 端到端运行接口；任务清单中的完整生成命令仍是后续设计。`models.py` 已实现 B1 契约，`llm_client.py` 已实现 B2 适配层，`prompts.py` 已实现 B3 上下文，源码工具已完成 C1/C1a，`generation.py` 已完成 C2 候选校验和落盘，D1/D2 执行及覆盖工具可用；`agent.py` 已实现 E1 首轮控制与动作决策，`reporting` 仍为骨架。

C1 可作为 Python 工具独立调用，不执行目标源码：

```python
from testgen_agent.tools import analyze_source

source = analyze_source("examples/validation.py")
print(source.canonical_json(indent=2))
```

默认只接受不超过 128 KiB 的 `.py` 文件，按 Python 编码声明读取，提取 1–5 个顶层同步函数、标准库导入、if/match/loop/try/raise 位置及函数体调用。语法错误包含行号；异步结构、相对/通配符导入、第三方依赖和顶层类会报告当前不支持；无目标函数会立即停止。只有绑定明确的同文件名称调用形成确认边；遮蔽、重绑定和动态调用会保留为未解析证据。

调用图辅助接口可单独使用：

```python
from testgen_agent.tools import (
    analyze_source, build_call_graph, candidate_entry_functions,
    find_call_cycles, find_explicit_data_flows,
)

source = analyze_source("examples/relationships.py")
print(build_call_graph(source))            # checkout -> calculate_total
print(candidate_entry_functions(source))   # 仅为候选入口
print(find_call_cycles(source))             # 递归强连通组件
print(find_explicit_data_flows(source))     # 仅嵌套调用/简单赋值
```

`models.py` 提供 `SourceInfo`、`RelationshipAnalysis`、`TestPlan`、`GeneratedTests`、`ExecutionResult`、`CoverageResult`、`AgentState`、`FinalReport` 及辅助类型。关系 Schema `1.1` 保存调用证据、入口、逐函数/关系策略、unit/collaboration 场景和有序数据传递；旧 `1.0` 单函数产物仍可读取。生成内容与工具实测结果分开；百分比和报告指标由计数及选定候选计算，未知值使用 `null`。接口、状态引用和序列化约定见 Design 第 4 节。

`llm_client.py` 提供 `DeepSeekClient.generate_tests(context)`：自动附加生成结果 Schema，使用 DeepSeek JSON Output，再用本地 Pydantic 严格校验。默认对瞬时故障最多重试 2 次，对格式错误最多修复 1 次，总 HTTP 请求不超过 4 次；400/401/402/403/404 立即失败。错误和公开配置不包含 Key、认证头或响应正文。B2 设计与实测见 Design 第 5 节。

```powershell
# 发送一次真实的固定 B2 结构化生成验证；可能产生 API 费用
.\.venv\Scripts\python.exe -m testgen_agent.b2_smoke
```

每次结果保存到 `outputs/b2/<run_id>/validation.json`。2026-09-26 实测 `deepseek-flash` 一次返回合法结构，耗时 1.573 秒、1125 tokens，无格式修复；精选证据为 [B2 验证结果](evaluation/b2_validation.json)。此命令使用固定轻量验证 Prompt，不等同于后续 B3 的正式 Prompt 或端到端 Agent。

`prompts.py` 的 `b3-v4` 把可信规则放入 system message，把源码、调用事实、确认图提示、行为说明、候选和工具日志放入带边界标记的 JSON 数据。首轮要求 Agent 自主选择入口、关系和单元/协作策略，图根仅作为候选；只分析嵌套调用和简单赋值等有明确源码证据的数据流，将动态调用与共享状态保持为不确定项。反馈轮携带此前关系、策略、候选、真实失败、缺失覆盖和剩余预算，并禁止删除有效断言、skip/xfail、广泛捕获异常或修改源码。D2 增加独立行/分支百分比及 `coverage_source_hints`，把缺失位置关联到源码和所属函数，保留负数代码对象退出弧的含义。

```powershell
# 向 DeepSeek 发送公开 relationships 样例源码、行为说明及正式 B3 Prompt；可能产生 API 费用
.\.venv\Scripts\python.exe -m testgen_agent.b3_smoke
```

每次结果保存到 `outputs/b3/<run_id>/validation.json`。该命令会向外部服务发送 `examples/relationships.py`、`examples/relationships.md` 和 Prompt 内容；仅在明确允许发送这些数据后运行。它会检查关系 Schema、源码证据、入口、策略及单元/协作场景。B3 真实调用尚未执行，不能仅凭离线测试宣称真实验收完成。

`generation.py` 提供 `generate_initial_candidate()`：一次取得结构化 `GeneratedTests` 后，校验计划证据、场景到真实测试函数映射、目标调用、有效断言、固定导入及禁止绕过项，并在宿主指定的新目录写入 `subject.py`、`rounds/01/test_subject.py`、`plan.json`、`candidate.json` 和脱敏 LLM 结果快照。无代码疑问和无效候选都会保留审计快照；无效代码不会写成可执行测试。有效工作区可交给 D1 的 `run_tests()`；生成和执行已接入 E3 的 Python 控制循环，CLI 尚未接入。

D1 可作为 Python 工具独立调用，工作区须已由宿主准备 `subject.py` 和 `rounds/01/test_subject.py`：

```python
from testgen_agent.tools import run_tests

# 替换成已有的 C2 工作区；有效候选也可直接传 artifacts.workspace。
result = run_tests("outputs/my-run", timeout=30)
print(result.canonical_json(indent=2))
print(result.all_passed)
```

`timeout` 接受 `1..300` 秒的整数，默认 30 秒。工具使用当前解释器和参数列表，只执行固定测试文件，关闭外部 pytest 配置、conftest 和自动插件加载；子进程仅继承必要 OS 环境，LLM Key 及自定义密钥变量不传入。每次在 `rounds/01/executions/run-*/` 保存独立的完整 stdout/stderr、结构化 pytest JSON、可用的 JUnit XML 和 `execution.json`。返回日志截断到约 16K 并标明截断，失败位置和主要诊断保留；超时终止子进程并保留最近完整的计数快照。

返回 `ExecutionResult` 区分通过、断言失败、运行异常、收集/导入错误、内部/用法错误、无测试、超时、启动失败和结构化结果不可用。`kind=passed` 仅表示 pytest 返回 0，验收应检查 `all_passed`；空测试、skip/xfail/xpass 或不完整结果都不能达到全通过。输入/布局错误抛出 `TypeError`、`ValueError` 或 `ExecutionWorkspaceError`，诊断文件 I/O 失败抛出 `ExecutionArtifactError`。执行工具默认使用首轮固定布局，E3 可通过 round_number=2/3 选择后续轮次；仅用于可信课程样例，进程隔离不提供恶意代码的安全沙箱。

D2 同时采集测试和覆盖结果：

```python
from testgen_agent.tools import run_tests_with_coverage

run = run_tests_with_coverage("outputs/my-run", timeout=30)
print(run.execution.kind, run.candidate_all_passed)
print(run.coverage.status, run.coverage.line_percent, run.coverage.branch_percent)
print(run.artifacts)
```

`run_tests_with_coverage()` 通过 coverage 启动同一份固定 pytest 候选，每次创建新的 `.coverage` 数据库，不追加或合并旧数据；导出命令显式选择该工作区的 `subject.py`，测试及 Agent 文件不计入分母。返回 `CoverageRunResult`，包含执行结果、`CoverageResult`、产物目录和源码提示。行/分支百分比分别由各自计数计算；分母为 0 返回 `None`，含义为“不适用”；采集不可用时状态为 `unavailable`、指标未知并有错误原因。覆盖达标与候选全通过是两个独立事实，失败候选可保留覆盖数据。

产物在 D1 诊断目录中追加 `.coveragerc`、本次 `.coverage`、原始 `coverage.json`、导出日志及诊断、`coverage_result.json`、`coverage_source_hints.json`、`run_result.json`。导出另有 `min(timeout, 30)` 秒时限；超时、导出/解析失败、错误统计范围或源码快照变化都会标记覆盖率不可用，保留已取得的执行结果。测试超时的数据库不用于报告。主机产物 I/O 失败仍用 `ExecutionArtifactError`，已保存的 `execution.json` 保留。

2026-09-29 D2 验收时全套 313 项自身测试通过，其中 D2 新增 37 项，D1 40 项及原有 C2 31 项均保留。D2 实测单侧分支为行覆盖 3/4（75%）、分支覆盖 1/2（50%），连续执行证明旧数据没有抬高新候选指标；覆盖异常、零分母、负数退出弧和实测反馈 Prompt 也经过验证。自动测试不发送真实 API 请求，合成适配器产物仍明确标注为离线测试数据。

## D3 执行与覆盖可信度验收

```powershell
# 仅运行本地手写样例，不调用 LLM
.\.venv\Scripts\python.exe -m testgen_agent.d3_validation
# 可另存精选证据；目标必须不存在，不覆盖已有证据
.\.venv\Scripts\python.exe -m testgen_agent.d3_validation --evidence outputs/d3-summary-new.json
```

入口将 [手写样例与人工期望](validation/d3/README.md) 分别交给正式工具和不加载 Agent 结果插件的原生 pytest/coverage 命令，独立读取 JUnit 与原始覆盖 JSON，逐项比对预先写好的计数、语句行和分支弧。每次创建新的 `outputs/d3/<run_id>/`，保留命令、源码/测试副本、原始日志、结构化记录及比对结果；`--output` 可选择产物根目录，`--timeout` 为受控超时样例设置 `1..10` 秒时限（默认 3 秒）。退出码 0 表示所有检查通过，1 表示结果不符，2 表示参数错误。

2026-09-29 实测六类样例（全通过、断言失败、运行异常、导入失败、空测试、超时）及三次不同候选连续执行全部符合人工期望，源码原件及失败诊断保留，超时进程已结束，空测试/异常/超时均不误报成功。两分支目标只统计四个语句和两个弧，连续覆盖为 100%/100%、75%/50%、75%/50%，根目录旧数据库保持不变。精选记录见 [D3 验证结果](evaluation/d3_validation.json)。D3 发现并修复了超时 call 尚未结束时的执行项漏计：现在在进入 call 阶段时原子保存快照。新增 15 项回归检查；当前全套 328 项以 `-W error` 通过。Windows 已实测，POSIX 分支尚未进行平台验收；这些受控样例不等于恶意代码安全沙箱。

## E1 状态与动作控制器

`agent.py` 提供 `run_initial_step(request, client=..., oracle_mode=..., tools=...)`：读取 `TaskInput.source_path` 和可选 `spec_path`，分析源码，调用适配器生成一次候选，校验后执行，返回 `ControllerResult`（状态、下一步动作、理由、动作摘要及原始候选产物）。`request.output_dir` 必须是新的独立工作区；显式传入 `behavior_specification` 可覆盖说明文件内容。`AgentTools` 可替换分析、生成和执行接口，便于离线验证。

`choose_action(state)` 根据真实执行、覆盖及模型已有关系/策略选择动作；`build_action_context(state)` 只准备当前允许的生成/修复/补充上下文，不发送请求。覆盖缺失关联到所属函数和传递调用者链，模型需说明补充单元边界或入口协作行为的依据。测试全通过且覆盖达标仍要检查已选协作关系是否有场景与有效断言；有疑问、断言失败、超时或预算耗尽会阻止无条件继续生成。E2/E3 已接入失败归因、有限修订执行和历史记忆，E4 已为 `run_agent()` 接入逐步轨迹。

```powershell
# 离线适配器 + 真实本地 pytest/coverage，不发送 LLM 请求
.\.venv\Scripts\python.exe -m pytest tests/test_agent.py -q -W error
```

2026-10-01 E1 新增 21 项检查通过，包含真实分支缺口导致补充动作、规格疑问/无效代码阻止执行、覆盖达标但协作场景缺失、有效断言门控及工具替换。合成模型输出只用于离线验收，不代表真实 LLM 或完整多轮 Agent 已验收。

## E2 失败分类与证据

pytest 工具在 `ExecutionResult.failures` 中保留真实异常类型、测试节点、阶段、位置和缺失模块，旧结果没有此字段时仍可读取。控制器按结构化来源区分生成测试的语法/导入/名称错误、环境缺依赖和需确认的源码/测试责任；未知归因转 `needs_review`，不直接假定测试写错。第三方依赖不会自动安装，超时、预算耗尽和重复无进展会停止。

`ActionDecision.status` 和 `issues` 保存任务状态与证据，`apply_decision()` 将问题追加到状态中。对于明确规格支持的断言失败，返回疑似源码缺陷并保留原预期和测试，禁止再构建生成上下文。当前自动规格核验仅支持单函数、单场景、单参数字面量相等断言，对照原始说明/docstring 的明确“输入/预期”两列表格；其他复杂规格、异常 oracle、协作流程和不确定/冲突情形保守请求人工确认。这不是通用规格语义验证。

```powershell
# 合成模型响应 + 真实本地执行，不发送 API 请求
.\.venv\Scripts\python.exe -m pytest tests/test_failure_analysis.py -q -W error
```

2026-10-01 E2 新增 29 项检查通过。真实折扣样例在输入 100、预期 90 时失败，控制器报告疑似源码缺陷并保留断言 90 和原源码；只请求一次离线适配器。E3 已接入有限多轮执行，完整报告仍留到 G。

## E3 任务记忆与有限反馈循环

通过 Python 接口 `run_agent(request, client=..., oracle_mode=..., tools=...)` 执行完整有限循环。`request` 为 `TaskInput`，`output_dir` 必须是新工作区，`max_rounds` 为 1–3；`client` 实现已有 `GenerationClient.generate_tests()`，可以是真实适配器或离线响应序列。传入真实客户端会向外部服务发送源码、行为说明和反馈；这里的验收只使用离线响应，不发送 API 请求。

每轮分别保存到 `rounds/01`、`02`、`03`，工具使用独立覆盖数据库。后续 Prompt 携带原始需求、历史关系/策略/场景、真实错误与覆盖缺口、已通过测试名称、最佳候选及剩余预算。宿主要求旧的已通过测试函数、场景及支持代码保持不变，补充场景另建测试函数；删除或改写会被拒绝。重复候选、新代码但覆盖无提升、规格疑问、疑似缺陷、超时、预算耗尽或不可恢复错误都会结束。

最佳候选优先选全通过且覆盖达标的版本，其次按覆盖可用、分支/行覆盖和通过数比较，同分保留早轮。追加候选无效时保留旧版本；失败缺陷证据始终留在历史与问题中。结束产物为 `state.json`、含真实状态/停止原因的 `summary.json`，以及选中候选的根目录 `test_subject.py`；没有可用候选时不伪造最终测试。E4 另保存详细 `trace.jsonl`；双格式最终报告仍留在 G。

```powershell
# 离线模型序列 + 真实多轮 pytest/coverage，不发送 API 请求
.\.venv\Scripts\python.exe -m pytest tests/test_agent_loop.py -q -W error
```

2026-10-01 E3 新增 34 项检查：三轮依次补正数、零值、负数分支并达到 100% 分支覆盖，另验证旧测试保护、无效候选回退、缺陷证据保留、无进展/预算/错误停止、实测用量累计、未知用量和任务隔离。真实 LLM 多轮效果尚未验收，当前 CLI 尚未接入。

## E4 逐步轨迹与可复现验收

`run_agent()` 在首次模型请求前创建独立 UUID、`run.json` 和 `trace.jsonl`。轨迹逐项追加 UTC 时间、轮次、状态、工具开始/完成/失败、输入与结果摘要、控制器动作及理由，引用各轮原始代码、执行日志和 coverage 产物。返回值及 `summary.json` 提供 `trace_file` / `metadata_file`。

公开配置、请求与返回模型、适配器报告的实际尝试次数、格式修复及用量均保留；未知值为 `null`。日志不复制 API Key、请求头或完整 Prompt。已有工作区拒绝覆盖；轨迹写入失败抛出 `TraceArtifactError`，保留已有事件。缺少 `run_finished` 表示轨迹未完整结束，多文件输出不承诺原子提交。

```powershell
# 手写离线模型响应 + 真实本地 pytest/coverage，网络请求为 0
.\.venv\Scripts\python.exe -m testgen_agent.e4_validation
# 专项回归
.\.venv\Scripts\python.exe -m pytest tests/test_tracing.py -q -W error
```

每次在新的 `outputs/e4/<UUID>/` 保存两组运行及 `validation.json`；`--output` 可选择输出根目录。2026-10-01 验收通过：反馈案例三轮补齐覆盖，记录 38 个事件；折扣缺陷案例一轮停止、保留断言，记录 16 个事件。精选证据见 [验收摘要](evaluation/e4_validation.json)、[反馈轨迹](evaluation/e4_feedback_trace.jsonl)、[缺陷轨迹](evaluation/e4_defect_trace.jsonl)。E4 新增 14 项检查，全套 **426 项**以 `-W error` 通过。此验收不代表真实 LLM 多轮效果。

## F1 自身测试与真实端到端验收

```powershell
# 自身测试使用 mock 模型；真实执行工具在本地子进程中验证
.\.venv\Scripts\python.exe -m pytest -q -W error
# 发送两项固定课程样例，使用现有 DeepSeek 配置，可能产生 API 费用
.\.venv\Scripts\python.exe -m testgen_agent.f1_validation --live
```

F1 新增 14 项检查，补齐多层关系位置、真实协作依赖/异常传播、历史与失败候选及报告契约一致性、产物篡改检测、Key 缺失及暂态错误重试计数。自身测试与生成测试分别放在 `tests/` 和独立运行工作区；两种覆盖数据分别统计。完整要求映射与复现步骤见 [F1 验收说明](validation/f1/README.md)。

2026-10-03 两项 `deepseek-flash` 真实验收通过：计算 6 条、协作 4 条测试全部通过，目标行覆盖均为 100%，分支不适用；各一轮/一次 HTTP，合计 11,311 tokens。首次响应暴露明确域外范围被写为阻塞问题，已升级 `b3-v5`，将范围备注记入 assumptions 并保留真正歧义的停止门控。失败和成功产物均保存，见 [F1 精选记录](evaluation/f1_validation.json)。该入口验收现有 `FinalReport` 契约，G2 的报告展示仍待实现；真实多轮与 F3/F4 效果评测尚未执行。

## F2 小型评测集

[F2 v1 评测集](benchmarks/f2/v1/README.md) 包含 12 个函数、8 个任务：数字边界/字符串/列表/异常与多分支各 3 个函数，开发 8 个函数、留出 4 个函数。订单和标签两组同文件协作案例提供独立的关系/入口/组合行为标注，另含独立函数对照。所有函数具正确参考实现、公开规格和手写预期；6 个已知错误版本含边界、空分支及函数间数据衔接错误。

```powershell
# 本地手写预期验证，不调用 API
.\.venv\Scripts\python.exe -m testgen_agent.f2_validation
# 自身检查和 AST 回归
.\.venv\Scripts\python.exe -m pytest tests/test_benchmark.py tests/test_call_analysis.py tests/test_source_analysis.py -q -W error
```

2026-10-03 八个正确任务的 69 条手写预期全部通过，六个错误版本均出现指定行为失败；原文件指纹不变，实际网络请求为 0。隐藏预期和人工评测标注不作为模型输入，四个留出任务未用于调 Prompt。精选记录见 [F2 验收结果](evaluation/f2_validation.json)。这些结果验证样例可用；F3/F4 的模型对照与缺陷检出实验尚未执行。

## A3 环境验证

```powershell
# 使用自己的配置发送一次真实 DeepSeek 最小请求，并执行手写样例
.\.venv\Scripts\python.exe -m testgen_agent.smoke
# 只运行本地手写样例及覆盖率采集，不调用 API
.\.venv\Scripts\python.exe -m testgen_agent.smoke --skip-llm
```

从工程目录运行（按上面的 editable 安装方式）。可用 `--model` 覆盖模型、`--env-file` 选择配置、`--output` 选择产物根目录、`--timeout` 控制本地工具单次超时。完整模式的最小请求关闭 thinking，最多 16 个输出 tokens，不自动重试；可能产生 API 费用。

每次创建唯一 `outputs/a3/<run_id>/`，保存手写测试与源码副本、pytest XML、coverage JSON、工具日志和 `validation.json`。该入口只验证环境，测试不是模型生成的。测试子进程不接收 API Key，原始源码不修改。

2026-09-26 实测：`deepseek-flash` 返回 HTTP 200 和 `OK`，耗时 1.267 秒、13 tokens；三条手写测试全部通过，目标源码行覆盖 2/2，无分支。保存的证据为 [验证摘要](evaluation/a3_validation.json)、[覆盖率 JSON](evaluation/a3_coverage.json)、[pytest XML](evaluation/a3_pytest.xml)。

完整验证两项都通过时 `a3_passed = true`、退出码 0；验证失败返回 1，参数错误返回 2。`--skip-llm` 本地通过时也返回 0，但 `a3_passed = false`，不能据此宣称真实 API 可用。网络失败、余额/权限错误或限流时保留失败摘要，不自动重试，不记录密钥或任意 API 响应正文。

## 样例和后续输出

- `examples/calculation.py` / `.md`：正常计算。
- `examples/validation.py` / `.md`：多分支校验及明确异常类型。
- `examples/discount.py` / `.md`：有意保留满 100 打折的边界缺陷。
- `examples/relationships.py` / `.md`：`checkout → calculate_total` 的确认直接调用、单元与协作策略样例。
- `examples/independent.py` / `.md`：同文件两个独立函数的单元策略对照，不应编造协作关系。

C2/E3/E4 已能在新工作区保存 `subject.py`、各轮 plan/candidate/LLM 快照、执行结果、覆盖率、任务状态、选中测试、结束摘要和逐步轨迹；双格式最终报告留到后续阶段。具体状态及验收约定见 Design；当前配置检查不会生成这些文件。

测试执行只面向本地可信课程样例；后续真实 DeepSeek 请求可能产生费用。仓库不包含真实 Key，使用者自行配置。
