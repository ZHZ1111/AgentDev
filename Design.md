# 测试生成 Agent 技术设计

> 当前进度：A1、A2、A3、B1、B2、C1、C1a、D1、D2 和 D3 已完成，C2 已完成实现和离线验收；B1 关系契约扩展及 B3 `b3-v4` 生成/反馈 Prompt 已完成离线验证。当前提供配置检查 CLI、DeepSeek 结构化生成适配层、正式 Prompt 构建入口、关系/策略数据契约、受限 AST 源码/调用分析、首轮候选宿主校验/落盘、独立 pytest 执行和目标覆盖工具、可重跑的独立可信度验收及兼容旧产物的模型；B3/C2 真实请求尚待明确授权将公开关联样例源码和说明发送给 DeepSeek。Agent 反馈循环尚未实现；本文其余任务接口、状态和输出目录仍是后续实现约定。A3/D3 的手写测试和 C2 的离线合成候选都不是模型生成结果。
> 2026-09-27 范围更新：Agent 自主判断同文件函数关联并规划单元/协作测试集。第 1.8 节范围已落实到第 4.8 节的 `1.1` 数据契约、第 6.5 节的 `b3-v3` Prompt、第 8 节的自动关系事实提取及第 9 节的首轮候选流程；端到端执行仍属于 D–F 阶段。

## 1. 范围与验收（A1）

### 1.1 产品目标与边界

输入一个小型 Python 源码文件及可选行为说明，Agent 使用源码工具提供的函数关系证据，自主判断关联、选择入口并规划单元/协作测试集，实际执行测试，读取失败和覆盖率反馈，在有限轮次内修复生成错误或补充场景，最后保存测试、报告和运行轨迹。用户不需要输入调用图或预先指定测试类型。

- 初版处理单个 `.py` 文件中的 1–5 个顶层同步纯函数，覆盖数字计算、字符串、列表和输入校验。
- 函数可以彼此独立或相互调用。初版重点支持静态可解析的同文件直接调用；明确的数据衔接可在源码或规格支持下规划测试，不凭函数名推断关联。
- AST 提供调用点和位置等证据，Agent 判断测试价值；动态调用记录未知，共享可变状态记录范围限制，暂不承诺完整动态分析或状态顺序测试。
- 被测文件允许使用标准库；生成测试允许使用标准库和 pytest。暂不支持外部依赖、相对导入、依赖原文件位置的资源读取、异步函数或复杂类结构。
- 只执行本地可信课程样例；临时工作目录和执行超时不构成完整安全沙箱。
- 不自动安装依赖，不修改原始源码，不处理大型仓库、多语言、服务或数据库测试，也不引入长期记忆或多 Agent 协作。
- 保留一次任务内的源码、行为依据、计划、候选和工具反馈；后续请求需要使用这些反馈。
- 最多执行 3 轮候选：首轮生成，加最多 2 轮反馈迭代。模型调用重试不能增加候选执行轮数。

本项目对应课程的测试生成方向：真实 LLM 生成、pytest 工具调用、反馈驱动的 Agent 循环和 CLI 属于核心验收；覆盖率、报告和缺陷检出提供验证证据。A1 只固定这些约定，不代表端到端功能已验收。

### 1.2 输入约定

相对路径以启动命令时的当前工作目录解析，宿主程序保存解析后的绝对路径。输入文件不被覆盖；输出目录不能覆盖源文件或说明文件。

| 输入字段 | 必填 / 默认 | 约束及含义 |
|---|---|---|
| `source_path` | 必填 | 已存在、可读的单个 `.py` 文件；按 Python 源码编码声明读取，必须通过语法检查并包含支持的目标函数。初版大小上限 64 KiB，超限报输入错误。 |
| `spec_path` | 可选，默认无 | 已存在、可读的 UTF-8 文本或 Markdown 文件，初版大小上限 64 KiB；说明输入域、返回值、边界及异常。显式提供但不存在或不可读时应报错，不能静默忽略。 |
| `output_dir` | 可选，默认 `outputs/` | 宿主程序在目录下创建唯一 `run_id` 子目录；不存在则创建，已有运行不覆盖。无法创建时报告输出错误。 |
| `model_config` | 必填，由配置层读取 | 包含服务商 `provider`、实际可用的模型标识 `model`、服务地址 `base_url`、API Key 的环境变量名 `api_key_env`、请求超时 `request_timeout_seconds`（默认 60 秒）。A2 按用户选择固定当前支持服务商为 DeepSeek，服务地址默认 `https://api.deepseek.com`；模型无默认值，须在 A3 验证实际权限。密钥不写入源码、报告或轨迹。配置来源见第 2 节。 |
| `max_rounds` | 可选，默认 `3` | 整数，范围 `1..3`，含首轮；`1` 表示一次性生成并执行。0、负数或超过 3 都报输入错误，不静默修正。 |
| `execution_timeout_seconds` | 可选，默认 `30` | 整数，范围 `1..300` 秒；限制单轮测试子进程运行时间，区别于模型请求超时。到期终止该次执行并记录超时。 |

配置不全、路径无效、语法错误、无目标函数或超出支持范围时，应在生成前给出原因。API 权限及模型可用性由真实请求验证，不能仅因字段非空而宣称通过。

预期行为依据的使用规则：

1. 提供说明文件时，结合说明与源码 docstring 建立测试依据；两者矛盾时记录具体冲突，进入 `needs_review`，不能擅自选择其中之一。
2. 没有说明文件但 docstring 足够明确时，以 docstring 为依据。
3. 二者都缺少明确约定时，可生成基于当前实现的特征测试，标记 `oracle_mode = characterization`；它们只描述现有行为，不能证明符合需求。
4. 有明确行为约定时标记 `oracle_mode = specification`。每个场景记录预期来源；说明未定义的输入不擅自补充异常类型或返回值。

### 1.3 输出约定

宿主程序决定文件名及路径，LLM 只返回测试内容和分析数据。每次运行采用下列布局（设计示例，尚未实现）：

```text
<output_dir>/<run_id>/
├── subject.py                  # 原始源码副本，固定导入名 subject
├── test_subject.py             # 最终选定候选，不是各轮代码的随意合并
├── report.md                   # 面向使用者的报告
├── report.json                 # 同一份报告数据的结构化输出
├── trace.jsonl                 # 状态、工具反馈、动作及简短选择理由
└── rounds/
    ├── 01/
    │   ├── test_subject.py      # 本轮候选；收到内容后即保留
    │   ├── test_plan.json       # 场景、测试函数及预期依据
    │   ├── execution.json      # 真实执行结果或未执行原因
    │   ├── stdout.txt
    │   ├── stderr.txt
    │   └── coverage.json       # 实际采集成功时才存在
    └── ...                     # 最多 03
```

- `test_subject.py` 使用 `from subject import <函数名>` 导入。配合相邻的 `subject.py`，从运行目录执行 `python -m pytest test_subject.py`；单独复制测试文件并不能保证导入成功。
- 若没有可用候选，顶层 `test_subject.py` 不生成，报告中的最终测试路径为 `null`；错误候选仍留在轮次快照中。不能用空文件代替成功结果。
- `report.md` 和 `report.json` 至少包含：输入及行为依据模式、模型标识与非敏感配置、最终状态、停止原因、实际轮数与调用次数、场景及依据、首轮和最终候选结果、最终文件与快照位置、未解决问题。
- `1.1` 数据契约已能在每轮计划和最终报告中保留函数关系、证据位置、单元/协作测试选择与理由、未解析关系及场景引用；报告文件的实际渲染与落盘仍由 F 阶段实现。
- 执行结果至少展示退出码、收集数、实际执行数、通过/失败/错误/跳过数和超时标记；模型不能填写这些实际测量值。
- 覆盖率至少展示目标文件、已覆盖/总语句、已覆盖/总分支、百分比、缺失行和分支。范围仅限 `subject.py`，不包含测试或 Agent 代码，不叠加不同轮的数据。
- 覆盖采集失败时标记为不可用并说明原因；分母为 0 时标记为不适用，不能填 100%。失败候选的覆盖率可展示，但需要同时标明该候选失败。
- `trace.jsonl` 记录时间、轮次、状态、动作、工具名称、输入/返回摘要和选择理由，不包含密钥或模型内部思维过程。
- 在输出目录可写时，即使任务失败也保存报告及已有证据；若目录本身不可写，至少向终端输出具体原因，不能承诺文件已保存。

### 1.4 独立结果维度

下列指标分别记录，不能互相替代：

| 维度 | 判定条件 | 不足以说明什么 |
|---|---|---|
| 生成文件 | 已写出候选测试内容；另记录是否通过语法校验 | 不代表 pytest 能导入、收集或执行。 |
| 候选可运行 | 语法/导入/收集成功，至少实际执行 1 条测试，执行正常结束，无超时、收集/fixture/框架错误；断言失败允许存在 | 不代表断言通过或源码正确。 |
| 测试全部通过 | 可运行，实际执行非空，失败及错误数均为 0；完成验收还要求无 skip/xfail 等绕过 | 不代表覆盖充分，特征测试也不证明规格正确。 |
| 覆盖达到目标 | 工具实测行覆盖率 ≥ 90%、分支覆盖率 ≥ 80%；无分支时分支目标不适用，行语句分母为 0 时不能验收为充分 | 不代表断言有效或没有 Bug；这些阈值是本项目停止策略，不是课程硬性要求。 |

仅跳过、仅 xfail、无测试收集的候选不能成为可用结果。混合执行中存在 skip/xfail/xpass 时不能进入 `completed`。后续执行结果结构需要单独记录这些绕过情况。

### 1.5 最终状态与判定顺序

状态描述本次任务的交付程度，不是对被测源码质量的认证。按以下顺序判断，保证结果互斥：

| 顺序 / 状态 | 判定条件 | 典型例子与必须保留的内容 |
|---|---|---|
| 1. `needs_review` | 存在明确规格支持的失败断言、规格/docstring 冲突，或影响结论的预期/失败归因无法确定 | 测试能运行，但“满 100 打九折”失败。保留输入、预期、实际、依据和失败候选；标记疑似源码缺陷，不能改断言迎合实现。冲突也可在执行前触发此状态。 |
| 2. `failed` | 不满足人工复核条件，且没有任何可用候选或输入无法进入流程 | 无效输入、模型请求失败且无历史候选、所有候选语法/导入错误、无测试、仅跳过或全部执行超时。列出错误和已完成步骤。 |
| 3. `completed` | 有可用最终候选，全部通过且无绕过，目标范围覆盖达到上述阈值，已规划的关键单元/协作行为有有效断言，无未解决错误或疑问，必要报告与轨迹成功保存 | 生成、执行、覆盖和交付均完成；特征测试模式仍必须明确标记其结论范围。新增策略完成校验需随 B1/E 扩展实现。 |
| 4. `partial` | 有可用候选、没有待人工复核的行为问题，但未满足 `completed` 的某项要求 | 全通过但覆盖不足/不可用，达到轮次上限、无进展，或后续 API/执行/报告错误导致未完成。保留上一轮可用候选并说明限制。 |

人工复核证据不会因后续 API 或覆盖率错误被降格成普通执行错误；报告同时列出这些错误。否则，不可恢复错误发生后是否存在历史可用候选，决定 `partial` 或 `failed`。

最终候选必须来自某个保存的轮次，并记录轮次号。对 `needs_review` 保留与复核问题相关的候选和证据；不能只展示此前通过的版本来掩盖有效失败。追加候选无效时可退回历史可用候选，但当前失败快照和未解决问题仍须出现在报告中。候选排序的具体实现留到 E 阶段。

停止原因另行记录，不与最终状态混用，例如 `coverage_target_met`、`round_limit_reached`、`no_progress`、`suspected_source_defect`、`ambiguous_specification`、`execution_timeout`、`unrecoverable_error`。达到预算上限不会自动变成 `completed`。

### 1.6 五个最小样例

样例源码和行为说明一一对应，docstring 与说明保持一致。均只使用标准 Python、无外部依赖、无文件或网络副作用。

| 类型 | 源码 / 说明 | 人工核验的关键预期 | 后续 Agent 验收目标 |
|---|---|---|---|
| 正常计算 | `examples/calculation.py` / `examples/calculation.md` | `calculate_total(12, 3) == 36`；`(0, 5)`、`(12, 0)` 都为 0 | 非空有效测试可运行，正常与零值边界通过；目标行覆盖达标，分支不适用。 |
| 多分支校验 | `examples/validation.py` / `examples/validation.md` | 0/59 为 `fail`，60/89 为 `pass`，90/100 为 `excellent`；-1/101 抛 `ValueError`，浮点/字符串/布尔值抛 `TypeError` | 覆盖类别边界和类型/范围错误。若首轮遗漏分支，反馈应引导追加；不能保证模型首轮一定遗漏。 |
| 明确规格下的缺陷 | `examples/discount.py` / `examples/discount.md` | 99 → 99，100 → **90**，101 → 90；源码在 100 时实际返回 **100** | 生成规格支持的断言，实际执行发现阈值错误，进入 `needs_review`，保留断言和疑似缺陷证据。 |
| 同文件直接调用 | `examples/relationships.py` / `examples/relationships.md` | `checkout → calculate_total` 为确认边；两函数 12×3 均为 36，零值为 0 | 分别规划乘法单元测试和入口协作测试，保存调用证据与选择理由，不 mock 同文件依赖。 |
| 同文件独立函数 | `examples/independent.py` / `examples/independent.md` | `rectangle_area(4,5) == 20`；`is_even(4)` 为真、`is_even(3)` 为假；两函数无关系 | 分别规划两个单元测试策略，不凭同文件、名称或类型编造协作流程。 |

计算样例的非负整数输入域是前置条件，域外行为未定义；不要求自动生成不存在的输入校验。校验样例明确排除 `bool`。折扣样例约定向下取整，避免浮点或金额舍入歧义。

说明文件中公开的输入输出是任务规格及人工核验锚点；后续评测的隐藏参考测试和错误变体答案不能混入模型输入。缺陷样例只展示一次确定的边界错误，不代表 Agent 已具备自动缺陷检出能力。

### 1.7 A1 验收记录

- 已固定六类输入、默认值和非法输入处理。
- 已固定最终测试、双格式报告、轨迹及每轮快照的输出约定。
- 已分开生成、可运行、全部通过与覆盖充分四个维度，并定义四个最终状态及判定优先级。
- 已准备四个源码文件和四个 UTF-8 行为说明，覆盖正常计算、多分支校验、明确规格缺陷和同文件直接调用。
- 2026-09-26 使用本地 Python 3.13.9 做三个源码文件的语法/导入检查及 32 项行为核验（含整数子类、异常类型和已知缺陷确认）：正常计算与校验符合规格；折扣的 100 边界确实得到 100，违反预期 90。该偏差为有意保留的课程样例。核验前后源码 SHA-256 一致，未产生缓存或修改源码。
- 2026-09-27 对新增关系样例执行 4 项行为核验：`calculate_total(12,3)`、`calculate_total(0,5)`、`checkout(12,3)`、`checkout(12,0)` 均符合说明；核验前后源码 SHA-256 一致。
- 2026-09-27 C2 增加独立函数对照样例；该新增不改写上述 A1 阶段验收事实，C2 验证见第 9 节。

本记录不替代 A3 的真实 API、样例 pytest 和 coverage 验收；A2 的工程环境和依赖验收见第 2 节。

### 1.8 Agent 自主分析函数关系与规划测试集（新增设计）

这项范围调整由用户于 2026-09-27 确认，是项目的初版设计选择，不是课程图片新增的硬性规定，也不改变此前已保存的验收结果。

分析分两层：源码工具负责提取可核验的事实，Agent 负责结合行为约定选择测试策略。工具返回函数、调用点、参数表达式和源码位置；Agent 输出关系解释、候选入口、单元/协作场景及选择理由，宿主校验名称和证据引用。

```mermaid
flowchart TD
    I[源码和可选行为说明] --> A[AST 提取函数与调用证据]
    A --> P[Agent 判断关系并选择测试策略]
    P --> U[单元场景]
    P --> C[有依据的协作场景]
    U --> G[生成同一 pytest 测试集]
    C --> G
    G --> R[真实执行与覆盖反馈]
    R --> D[Agent 决定修复或补充的场景]
    D --> G
    R --> F[报告关系 选择理由 结果与限制]
```

具体判断约定：

1. **直接调用**：只对名称绑定可确认的同文件目标函数建立已确认调用边。`ast.Call` 的名字恰好与函数同名还不够，参数/局部变量遮蔽、重新绑定等情况应标记未解析。
2. **数据衔接**：源码表达式如 `b(a(x))`、可追踪的简单变量传递或明确行为说明，可以提供关系依据；仅仅返回值类型相同或名称相似不能证明组合工作流存在。
3. **共享状态**：保存读写证据并标记当前纯函数范围限制，不把状态重置或调用顺序测试声称为初版已支持能力。
4. **未知关系**：别名、高阶函数、动态分派等初版无法解析时保留表达式、位置和未知原因。没有发现边不等于证明完全独立。
5. **入口选择**：图中无入边节点是候选入口而非必然业务入口；结合规格选择。递归或环路检测后不无限展开调用链，也不保证运行时终止。

测试策略以额外可验证行为为依据，不按图中的每条边机械生成测试。直接调用场景中默认调用真实入口和真实依赖，测试异常传播、条件分支和结果组合；内部函数的边界可以单独测试。源码之外的显式数据链只有在行为依据充分时才顺序调用相关函数。

示例：对 `checkout → validate_order` 和 `checkout → calculate_total`，分别规划校验与计价的单元场景，再考虑调用 `checkout` 的合法订单总价和非法输入传播场景。测试需要根据给定源码和规格生成，不预设所有项目都采用这些函数名或工作流。

新增验收案例包括：同文件独立函数、直接/多层调用、明确数据传递、名称遮蔽、未知动态调用及递归。报告应说明关系、依据、测试选择和未知项。已有 A1 的三个单函数样例保留，不因新增功能失去兼容。

修订预算为 58h：C 阶段 10h、E 阶段 9h、F 阶段 8h，缓冲 3h，其余阶段不变。关系契约和 Prompt 扩展在 C 阶段预算内先完成，CLI 不增加要求用户标注关系的参数。

## 2. 工程骨架与 DeepSeek 配置（A2）

### 2.1 环境及依赖

2026-09-26 在 Windows x64 上创建独立 `.venv`，使用 CPython **3.13.9**（虚拟环境内 pip 25.2）。项目元数据限定 `>=3.13,<3.14`，当前未宣称其他 Python 版本或平台已验证。

| 依赖 | 已安装并验证的版本 | 职责 |
|---|---|---|
| httpx | 0.28.1 | DeepSeek API 的同步 HTTP 请求；离线测试使用 MockTransport |
| pydantic | 2.13.5 | 配置类型、范围和必填项校验；后续用于模型响应结构校验 |
| python-dotenv | 1.2.3 | 读取指定 UTF-8 `.env` 文件 |
| pytest | 9.1.1 | Agent 自身测试及后续生成测试的执行框架 |
| coverage | 7.16.1 | 后续目标文件行/分支覆盖率采集 |
| setuptools / wheel | 84.0.0 / 0.48.0 | 构建及 editable 安装 |

`pyproject.toml` 固定直接与构建依赖，`requirements.lock` 固定本次安装的 **21 个直接、传递和构建依赖**；不包含本地项目或 pip。安装顺序为先安装锁文件，再以 `--no-index --no-build-isolation --no-deps -e .` 安装本地工程，防止构建阶段另行解析依赖。锁文件是已验证环境的版本快照，未做跨平台或包哈希锁定；具体复现命令见 README。

pytest 默认只收集 `tests/`，防止把被测样例或未来生成测试混入 Agent 自身验证。`pyproject.toml` 中的 coverage 设置针对 Agent 自身；D 阶段的执行工具必须另行限定本次 `subject.py`，不能沿用 Agent 的统计范围。

### 2.2 已建立模块与入口

```text
AgentDev/
├── pyproject.toml / requirements.lock
├── .gitignore / .env.example
├── README.md / Design.md / TASK_CHECKLIST.md
├── src/testgen_agent/
│   ├── __init__.py / __main__.py
│   ├── cli.py / config.py / llm_client.py
│   ├── models.py / prompts.py / generation.py / agent.py / reporting.py
│   └── tools/
│       ├── __init__.py
│       ├── source_reader.py / code_analyzer.py / test_runner.py
├── tests/test_config.py
├── examples/                  # A1 的三个样例及说明
└── evaluation/                # 后续评测目录
```

- `python -m testgen_agent` 和安装后的 `testgen-agent` 使用同一个 CLI 入口；当前实现 `--help`、`--version`、`--check-config` 及配置覆盖参数。
- `config.py` 完成配置读取、校验与脱敏摘要，`llm_client.py` 提供配置驱动的 HTTP 客户端工厂；客户端创建不会发送请求。
- A2 阶段创建了 `models`、`prompts`、`agent`、`reporting` 及源码/执行工具骨架；此后 `models`、`prompts`、源码分析工具、`generation` 和 `test_runner` 已分别在 B1、B3、C1/C1a、C2 和 D1 实现。`agent`、`reporting` 仍保留为后续阶段骨架；生产模块不包含伪装为真实模型或真实执行的固定成功结果。
- `outputs/` 和临时工作目录由后续实际运行时创建，并由 `.gitignore` 排除；设计内容统一写入本文件，没有创建 `docs/scope.md`。

### 2.3 配置来源与约束

优先级：**命令行覆盖 > 进程环境变量 > 选定 `.env` 文件 > 默认值**。不搜索父目录，不通过 dotenv 修改 `os.environ`，不展开 `${...}`。支持 UTF-8 及 UTF-8 BOM；显式指定不存在的文件时报配置错误，默认 `.env` 不存在时仍可使用环境变量。

| 配置项 | 环境变量 | 默认值 / 校验 |
|---|---|---|
| provider | `LLM_PROVIDER` | `deepseek`；当前拒绝其他服务商 |
| model | `LLM_MODEL` | 无默认值；必须填写非占位符模型标识 |
| base_url | `LLM_BASE_URL` | `https://api.deepseek.com`；有效 HTTP(S) 地址，不含用户名、密码、查询或片段 |
| api_key_env | `LLM_API_KEY_ENV` | `DEEPSEEK_API_KEY`；必须为合法环境变量名 |
| api_key | 上一行指定的变量 | 无默认值；缺失、空值、占位符或含空白的 Key 均拒绝 |
| request_timeout_seconds | `LLM_REQUEST_TIMEOUT_SECONDS` | 60；1..600 的整数 |
| max_rounds | `AGENT_MAX_ROUNDS` | 3；1..3 的整数 |
| execution_timeout_seconds | `TEST_EXECUTION_TIMEOUT_SECONDS` | 30；1..300 的整数 |

命令行可覆盖除 Key 明文外的上述设置；Key 只能来自文件或环境变量。Key 使用 `SecretStr`，从对象 repr 和序列化输出排除；公开摘要仅额外返回 `api_key_configured` 标志。配置错误按字段给提示，不输出原始被拒绝值。

配置检查返回 0 表示本地校验通过；参数或配置错误返回 2。此状态只反映配置，不等同于 A1 的任务 `completed`。缺少运行模式时 CLI 提示使用 `--check-config` 或 `--help`；当前不提供源码输入或生成运行命令。Windows 非终端输出统一采用 UTF-8，以便重定向后正确读取中文。

### 2.4 DeepSeek 接入约定

按用户选择使用 DeepSeek 原生 HTTP 调用，不引入 Agent 框架。官方接口为 Bearer 认证的 `POST /chat/completions`，请求体包含模型及消息；本地客户端使用 httpx，后续由独立适配层组织请求及解析响应。[DeepSeek 首次调用说明](https://api-docs.deepseek.com/zh-cn/)、[Chat Completions 接口](https://api-docs.deepseek.com/api/create-chat-completion/)

客户端从配置读取地址、密钥和超时，以相对路径 `chat/completions` 发起调用，保留可配置的 `/v1` 前缀，不跟随重定向；HTTPX 默认不自动重试。A2 不实现真实生成方法、退避策略或响应修复，这些预算和错误处理在 B2 中实现。

`request_timeout_seconds` 当前设置 HTTPX 的连接、读、写及连接池等待超时，不表示整个响应的总墙钟时限；D1 的 `run_tests()` 已接受单轮测试子进程的执行超时（默认 30 秒），控制器后续将传入 `execution_timeout_seconds`，两者不混用。

模型名没有默认值，`.env.example` 中仅提供模型和密钥占位符，使用者必须替换。官方文档列出的模型只是选择参考，不能替代账号真实权限验证；最终模型标识、测试日期、延迟和用量在 A3 记录。A2 不保存真实 Key，不发送付费 API 请求。

### 2.5 A2 验收记录

- `.venv` 已创建；项目 editable 安装成功，两个入口的帮助/版本可用。
- 直接及传递依赖已安装，21 项版本锁文件在当前环境解析通过，`pip check` 返回 `No broken requirements found`。
- 24 项自身测试通过，覆盖文件/环境/命令行优先级、占位符与必填项、轮次/超时边界、敏感信息隐藏、UTF-8 重定向输出，以及离线 HTTP 客户端的路径、认证和超时设置。
- `.gitignore` 排除 `.env`、虚拟环境、缓存、打包目录、运行目录及覆盖率中间文件；`.env.example` 保留为可分发配置示例。
- 真正的模型访问、手写样例 pytest 和 coverage JSON 验证仍属于 A3，没有提前勾选。

## 3. 真实 LLM 与测试环境验证（A3）

### 3.1 验证方式与可复现入口

新增 `python -m testgen_agent.smoke` 作为阶段 A3 的环境验证入口，与未来的测试生成 Agent 分开。其源码位于 `src/testgen_agent/smoke.py`；手写测试位于 `validation/handwritten/test_calculation.py`，不参与 `tests/` 的 Agent 自身测试收集。

完整验证从当前 `.env` / 环境变量读取配置，也可通过 `--model` 覆盖模型；仅本地验证时使用 `--skip-llm`，不需要密钥。每次运行创建唯一 `outputs/a3/<run_id>/`，保存源码副本、手写测试副本、pytest JUnit XML、coverage JSON、工具输出和 `validation.json`。

```powershell
.\.venv\Scripts\python.exe -m testgen_agent.smoke
# 仅验证本地工具，不发送 API 请求
.\.venv\Scripts\python.exe -m testgen_agent.smoke --skip-llm
```

完整模式只发送 **1 次**非流式 Chat Completions 请求，不自动重试；提示为 `Reply with exactly OK and nothing else.`，关闭 thinking，`max_tokens=16`。本次验收条件为 HTTP 200、内容为 `OK`、结束原因 `stop`，且响应耗时不超过 30 秒。这是一条最小连通性请求，不上传项目源码，也不验证模型生成测试的质量。

本地工具验证将 `examples/calculation.py` 复制为 `subject.py`，将手写测试复制为 `test_subject.py`。使用当前虚拟环境解释器运行 `coverage run --branch -m pytest` 并导出 JSON；显式传入独立的 pytest/coverage 配置和目标文件过滤，防止继承工程的 Agent 覆盖范围。测试子进程只接收必要 OS 环境变量，不接收 LLM Key，且限制测试执行及覆盖导出单次超时（默认 30 秒）。

`--skip-llm` 成功时退出码为 0，但结果中 `llm.status = skipped`、`a3_passed = false`，不能据此宣称 A3 全部完成。完整模式必须两项验证均通过才返回 0；任一失败返回 1。输入参数无效返回 2。配置/API 错误不记录认证头、密钥、任意响应正文或异常原文。

### 3.2 DeepSeek 实测记录

测试日期：**2026-09-26 19:39（Asia/Shanghai）**，对应 UTC `2026-09-26T11:39:08.944869+00:00` 的运行开始时间。此前以本地 Key 查询 `GET /models`，HTTP 200，实际返回 `deepseek-flash` 和 `deepseek-v4-pro`；选用前者进行真实请求，成功后将本地忽略文件 `.env` 的模型占位符替换为 `deepseek-flash`，原 Key 未改动。

| 项目 | 实测结果 |
|---|---|
| 服务商 / 地址 | DeepSeek / `https://api.deepseek.com` |
| 请求模型 / 响应模型 | `deepseek-flash` / `deepseek-flash` |
| 请求方式 | `POST /chat/completions`，非流式，关闭 thinking |
| 请求次数 | Chat 请求 1 次；另有一次成功的模型列表查询 |
| HTTP 状态 / 输出 | 200 / `OK` |
| 结束原因 | `stop` |
| 响应耗时 | 1.267 秒（含连接和响应读取） |
| 实际用量 | prompt 12、completion 1、total 13 tokens |
| 缓存用量 | hit 0、miss 12 tokens |

用量直接取自服务返回值，未估算费用。本次耗时低于 30 秒的验证阈值，只代表这一次最小请求，不能证明较长测试生成请求也有相同延迟。Key、认证请求头和完整请求/响应未保存到可提交证据中。

### 3.3 手写 pytest 与 coverage 实测记录

手写三条测试：普通购买 `12 * 3 == 36`；零价格/零数量（含二者都为零）；大整数 `1000000 * 1000000 == 1000000000000`。均以 A1 的行为说明为依据，未使用 LLM 返回固定测试伪装成生成结果。

| 项目 | 实测结果 |
|---|---|
| Python / pytest / coverage | 3.13.9 / 9.1.1 / 7.16.1 |
| pytest / coverage JSON 导出退出码 | 0 / 0 |
| 测试数 / 通过数 | 3 / 3 |
| 失败 / 错误 / 跳过 | 0 / 0 / 0 |
| 覆盖范围 | 仅 `subject.py`；不包含测试或 Agent |
| 行覆盖 | 2 / 2，100%；执行行 4 和 9，缺失行为空 |
| 分支覆盖 | 总分支 0，不适用；规范化结果使用 `null`，不写为 100% |
| 原始源码 | 核验前后 SHA-256 一致，未修改 |

原始 coverage JSON 对无分支情形可能给出百分比 100；验收摘要依据分母为 0 显示不适用。该样例只确认导入、执行及目标文件统计可用，不替代 D 阶段的失败、超时和多分支统计验证。

### 3.4 保存的验收证据与进度

- [evaluation/a3_validation.json](evaluation/a3_validation.json)：两项真实验证的结构化结果，含日期、模型、耗时、用量、版本及源码摘要；`a3_passed = true`。
- [evaluation/a3_coverage.json](evaluation/a3_coverage.json)：该次工具导出的原始目标覆盖 JSON。
- [evaluation/a3_pytest.xml](evaluation/a3_pytest.xml)：该次 pytest 的 JUnit XML。
- 本地完整产物目录：`outputs/a3/20260926T113908Z-0315ebb0/`，由 Git 忽略；上述精选证据保留在可提交目录。

Agent 自身测试扩充至 **33 项并全部通过**，新检查覆盖最小请求、实际用量读取、认证/余额/限流失败、空/截断/错误响应和子进程环境隔离；这些自动测试使用 MockTransport，不发送 API 请求。真实 API 验收来自本节单独记录的服务响应。

阶段 A 的范围、环境和真实 API/工具验证已完成。B1、B2、B3 的后续记录分别见第 4、5、6 节；后续 Agent 流程仍未实现。

## 4. 模块间数据结构（B1）

### 4.1 核心数据契约

实现位置：`src/testgen_agent/models.py`，沿用已验证的 pydantic 2.13.5，不增加依赖。下表中的生产/消费关系是后续模块必须遵守的接口，当前完成的是类型、结构校验和序列化。

| 核心结构 | 主要字段 | 生产方 → 消费方 |
|---|---|---|
| `SourceInfo` | `source_path`、`source_code`、`encoding`、`functions`、`imports`、`branches`、`call_sites`、`direct_calls`、`unresolved_calls` | C1 源码工具 → Prompt / 控制器 |
| `TestPlan` | Schema 版本、目标与入口函数、oracle、关系分析、逐函数/关系策略和场景；场景分开记录行为类别与 unit/collaboration 类型 | B2/B3 模型输出 → 生成校验 / 反馈上下文 |
| `GeneratedTests` | `plan`、`code`、`mappings`、`assumptions`、`questions` | B2 适配层校验后的模型内容 → C2 候选写入 / 控制器 |
| `ExecutionResult` | `kind`、`exit_code`、收集/执行/各结局计数、stdout/stderr、超时、日志截断及耗时 | D1 执行工具 → 控制器 / 报告 |
| `CoverageResult` | `target_file`、可用状态、覆盖/总语句及分支、缺失行/弧、采集错误；百分比由计数计算 | D2 覆盖工具 → 控制器 / 报告 |
| `AgentState` | 原始 `request`、源码和行为说明、依据模式、当前轮次、历史候选、最佳可用轮次、下一步动作、停止原因、问题、调用数和用量 | 宿主控制器维护 → 下一轮上下文 / 报告 |
| `FinalReport` | `schema_version`、任务状态、停止原因、输入、所有轮次、选定轮次、最终测试/轨迹路径、未解决问题、调用数及用量；`metrics` 从选定轮次读取 | 宿主控制器 → G2 Markdown/JSON 报告 |

契约的数据流如下；实际生成、执行和决策流程仍由后续阶段实现：

```mermaid
flowchart LR
    I[TaskInput] --> S[SourceInfo]
    S --> G[TestPlan / GeneratedTests]
    G --> T[ExecutionResult / CoverageResult]
    G --> R[CandidateRound]
    T --> R
    R --> A[AgentState]
    A --> F[FinalReport]
```

辅助类型将含义明确的记录独立建模：`FunctionInfo`、`ImportInfo`、`SourceBranch`、`ScenarioInput`、`ExpectedBasis`、`TestScenario`、`TestCaseMapping`、`BranchArc`、`CandidateRound`、`Issue`、`TokenUsage`、`ReportMetrics`。`TaskInput` 保留输入和运行预算，`ModelInfo.from_config()` 只提取服务商、模型、地址及请求超时，不包含 Key。

### 4.2 模型内容与工具实测结果分离

模型生成内容统一按 `GeneratedTests` 校验。它的根字段只有计划、代码、对应关系、假设和疑问；不接受执行结果、覆盖率、实际通过数、最终状态、调用次数或输出路径。嵌套对象也禁止额外字段，不能通过场景参数对象夹带指标字段。

场景参数以 JSON 可表达的值记录：`args` 为位置参数序列，`kwargs` 为参数名到值的映射。正常、边界、异常、分支场景使用固定类别；预期依据必须标记为说明规格、docstring 或当前实现假设，并给出具体说明。特征测试模式的场景只能标记当前实现假设。

计划目标、场景 ID 和测试函数对应关系需要一致：目标和场景 ID 唯一，场景函数属于计划目标，映射中的 ID 恰好覆盖计划场景，一个测试函数可以通过参数化对应多个场景。映射名须为 `test_` 开头的 Python 标识符。源码元数据的目标函数限定 1–5 个，名称不重复，行号在源码范围内。

全部预期无法确定时，允许返回 `code = null`、空映射和非空 `questions`，保留疑问而不编造测试。返回代码时必须有非空计划及完整映射。测试代码的 AST、导入、有效断言及映射函数是否真实存在仍在 C2 校验。

字段分离不能证明数据实际来自一次工具调用。B2 只解析模型的 `GeneratedTests`；D 阶段必须从真实工具返回值构造 `ExecutionResult` / `CoverageResult`，宿主负责其来源与对应轮次。

### 4.3 执行结果的口径和约束

计数使用非负严格整数，不将字符串、布尔值或小数转换成计数。未观测到的计数为 `null`，超时或进程未启动时不能默认填写“通过 0 条”来假装已取得统计。

`kind` 分别表示 `passed`、`assertion_failed`、`execution_error`、`collection_error`、`internal_error`、`usage_error`、`interrupted`、`no_tests`、`timeout`、`launch_error` 和 D1 新增的 `result_error`。普通 pytest 结果与对应退出码保持一致；超时类型和 `timed_out` 标志必须相符，进程未启动时退出码为 `null`，且不允许报告非零测试项计数。`result_error` 保留已观测的实际退出码，表示结构化诊断缺失、矛盾或无法分类，不能成为可运行/全通过结果。

- `collected`：收集到的不同测试项数，参数化实例分别计数。
- `executed`：实际进入 call 阶段的不同测试项数，由工具独立观测；setup 失败和纯跳过不计入，call 阶段发生的 xfail 可计入。
- `passed`、`failed`、`errors`、`skipped`、`xfailed`、`xpassed`：结束运行时的互斥最终结局。setup/teardown 错误优先记为 errors，其他诊断保留在日志；不能将一个测试的 call 通过与 teardown 错误重复计为两个结局。
- 对 `passed` / `assertion_failed` / `execution_error` 的完整执行，所有计数必须已知，结局合计等于收集数。收集错误等非完整执行允许计数未知；其 errors 可表示收集错误，不套用测试项合计约束。

`runnable` 和 `all_passed` 是只读派生字段。可运行要求无超时/框架错误、确实执行非空普通测试；断言失败仍可运行。仅 skip/xfail/xpass 的候选不能成为可用结果；混合跳过、xfail 或 xpass 的候选不能达到全部通过验收。全通过还要求非空测试、所有收集项实际通过、无失败/错误/绕过。

### 4.4 覆盖率与未知指标

`CoverageResult.status = available` 时，语句和分支计数必须已知，已覆盖数量不能超过总数量，缺失位置不得重复，缺失数量须与总数减覆盖数一致。缺失行号是源码位置，不能错误地以“语句数”为行号上限。`BranchArc` 使用有符号行号，保留工具可能给出的负数退出弧，拒绝 0 行号。

采集不可用时使用 `status = unavailable` 和错误原因，计数均为 `null`，不填猜测值或伪造缺失位置。行/分支百分比是只读计算字段；分母为 0 时返回 `null`。`meets_target` 按 A1 的 90% 行、80% 分支策略计算；无分支时不应用分支阈值，行分母为 0 时不能达到目标。

覆盖数据可属于断言失败的候选，因此单独记录在同一轮快照中；报告同时保留执行失败信息。实际目标文件过滤、新数据隔离及采集错误处理由 D2 完成。

### 4.5 历史快照与状态引用

`AgentState.history` 是 `CandidateRound` 的有序元组，轮次从 1 连续编号，长度不超过输入预算；`current_round` 与历史长度一致，初始状态为 0。可以先保存待处理的轮次快照，再以经校验的新快照补入生成、执行和覆盖结果。尚未执行时使用 `execution = null`，未采集时使用 `coverage = null`。

执行结果必须关联已生成、未被候选校验判定无效的代码；覆盖记录需要同轮执行记录。生成计划的函数须来自已分析源码，依据模式不得改变原始任务模式。最佳可用轮次必须引用真实历史中的可运行候选，不自动选择或重新排序候选。

`Issue` 保存问题类别、摘要、证据及可选的轮次/场景引用；提供引用时检查其存在性。后续候选无效时，历史保留其校验错误，可以继续指向上一轮可用候选；规格失败的执行和疑似缺陷证据也保留在快照中。停止原因已设置时，下一步动作只能为 `finish` 或 `request_review`。

模型禁止直接属性赋值，历史及结构化列表使用元组；`updated(**changes)` 会重新校验修改后的完整对象。JSON 参数内部的 dict/list 仍可变，后续 E 阶段归档应保存独立快照，不能依赖浅层冻结实现深层不可变。不要以绕过校验的 `model_construct()` 或 `model_copy(update=...)` 更新任务状态。

### 4.6 最终报告与序列化

旧报告使用版本标识 `1.0`；关系扩展报告使用 `1.1`。两者都要求选定轮次和最终文件路径同时存在或同时为空。`1.1` 报告在存在生成候选时必须保留 `SourceInfo`，并交叉校验关系证据；旧 `1.0` 单函数产物继续按原契约读取。选定轮次必须可用；报告的指标从该轮执行/覆盖记录读取，调用次数来自宿主，Token 用量未知时使用 `null`，已知组件合计须一致。

状态自洽校验包括：

- `completed`：选定候选全部通过、覆盖达到目标、提供轨迹路径、没有未解决问题/疑问，停止原因为覆盖目标达成。
- `partial`：存在可用最终候选，且没有需要人工复核的行为问题；可保留失败的后续候选及运行限制。
- `needs_review`：保留疑似源码缺陷/规格歧义问题，或选定候选的未解决疑问；在规格冲突导致尚未执行时，也可以没有最终候选。
- `failed`：没有历史可用候选，也没有需要优先人工复核的证据；最终测试路径为空。

这些校验保证字段和值的关系一致。实际失败归因、状态选择、候选排序和停止决策仍由 E 阶段控制器执行；文件是否真实落盘由工具和报告模块验证，数据模型本身不读写输出文件。

所有核心结构支持 JSON Schema：`model_json_schema(mode="validation")` 用于输入校验，`mode="serialization"` 描述含只读派生指标的输出。模型生成边界使用 `GeneratedTests` 的输入 Schema。

```python
# 从模型响应解析生成内容（实际 API 适配在 B2 实现）
generated = GeneratedTests.model_validate_json(response_text)
# 保存可重新校验的原始字段快照，不重复存储派生指标
snapshot = state.canonical_json()
restored = AgentState.model_validate_json(snapshot)
# 输出报告时包含从同一份结果计算的只读 metrics / 百分比
report_data = report.model_dump(mode="json")
```

`canonical_json()` 采用 `round_trip=True` 排除派生字段，路径转换为字符串、元组转换为 JSON 数组并保留中文；恢复时重新执行结构校验。普通报告输出包含派生字段，这些字段不作为输入接收，避免写入与计数不一致的百分比。实现遵循 [Pydantic 序列化](https://docs.pydantic.dev/latest/concepts/serialization/) 和 [模型校验](https://docs.pydantic.dev/latest/concepts/validators/) 接口，已针对本地锁定版本验证。

### 4.7 B1 验收记录

2026-09-26 完成七个核心模型、辅助记录、动作/停止原因/状态枚举及公共模型配置快照。新增 **60 项数据契约测试**，加上原有 33 项，总计 **93 项全部通过**；以 `-W error` 执行，无警告，`pip check` 通过。

验收覆盖：七类 JSON Schema 和原始字段序列化往返、中文保留、非法/额外字段、生成结果与工具指标隔离、场景映射、严格计数、执行失败及绕过、零分母与覆盖不可用、历史预算和引用、退回旧候选、规格失败需复核、最终状态及指标一致性。测试中的任务和缺陷证据均为合成数据，不宣称已执行 Agent 端到端任务。

另外将已有 A3 的真实 JUnit XML、覆盖率 JSON 和服务用量读入对应数据模型，核对三条测试通过、2/2 行覆盖、无分支和 13 tokens；新契约与已保存工具证据一致，验证未发送 API 请求。A3 原始产物及本地 `.env` 未修改。

B1 仅固定并验证模块间的数据结构；B2、B3 的实现与验收记录见第 5、6 节，C/D/E 和正式报告输出仍按任务清单继续实施。

### 4.8 关系与测试策略数据契约扩展（已实现）

2026-09-27 在 `models.py` 增加关系 Schema `1.1`。旧计划省略版本时按 `1.0` 解析；`1.0` 禁止夹带关系字段，`1.1` 强制完整关系策略。历史 A3/B2 证据无需改写，新产物可以显式迁移。

| 扩展对象 | 已实现信息 | 来源与校验要求 |
|---|---|---|
| `SourceInfo` | `CallSite`、`DirectCall`、`UnresolvedCall` 三组事实 | 调用点保存稳定 ID、caller、表达式、参数表达式、行号和片段；确认边与未知原因引用调用点，校验位置、函数名、唯一性和互斥性 |
| `RelationshipAnalysis` | 关系 ID、`direct_call/data_flow/shared_state/unknown`、涉及函数、证据、`confirmed/candidate/unknown`、未决问题 | 源码/规格/docstring 证据分开保存；unknown 必须保留问题，confirmed 不能使用未解析调用点 |
| `TestPlan` | `schema_version=1.1`、`entry_functions`、`relationships`、`strategy` | 每个目标函数和每个关系恰有一条 `unit_test/collaboration_test/not_selected` 决策及理由；入口与引用必须来自计划目标 |
| `TestScenario` | `test_kind`、`involved_functions`、`relationship_ids`、可选有序 `ScenarioStep` | category 与 test_kind 分维度；协作场景需至少两个函数和非 unknown 关系；步骤结果只能引用此前步骤 |
| `AgentState` / `FinalReport` | `schema_version`，报告增加 `source_info` | `validate_plan_against_source()` 将模型关系与 AST 事实交叉校验；状态/报告和各轮计划版本一致，`1.1` 报告保留证据来源 |

对入口调用链场景，原 `target_function` 仍表示实际调用的入口，例如 `checkout`，`inputs` 仍是入口输入；`involved_functions` 说明依赖。对没有封装入口的显式数据链，需用有序步骤表示先调用 A，再把输出传给 B，不能用单个输入对象伪装已表达完整组合。

协作测试与执行工具的关系应保持诚实：计划中的涉及函数是设计信息，实际执行路径可能因条件提前退出。工具未采集逐函数调用轨迹时，不把计划宣称为所有依赖都实际执行；模块级覆盖率也不能证明某条调用链或组合断言已被验证。

新增 `tests/test_relationship_models.py` 共 **27 项**测试，覆盖调用点分类、关系置信度、策略/场景一致性、调用方向、场景两维分类、关系引用、步骤顺序、旧 `1.0` 兼容、状态/报告版本和未知调用不得升级为确认关系。B1 原 60 项契约测试保持通过；扩展后的总测试数见第 6.4 节。自动 AST 提取事实仍由 C1a 实现，当前契约测试使用合成的工具事实。

## 5. DeepSeek LLM 适配层（B2）

### 5.1 统一接口与职责边界

实现位置为 `src/testgen_agent/llm_client.py`。业务入口是 `DeepSeekClient.generate_tests(context)`；也提供同名模块函数，便于不复用客户端对象的调用方使用。输入 `GenerationContext` 只包含 `system_instruction` 与 `user_prompt`，输出 `LLMGenerationResult` 包含经本地校验的 `GeneratedTests`、请求/响应模型、尝试次数、格式修复次数、总耗时、每次成功响应记录和累计 token 用量。

B2 不决定完整测试策略。B3/E 负责生成或反馈 Prompt 的实际内容，适配层负责：

- 从 `AppConfig` 读取服务地址、模型、Key 和请求超时；创建不含 SDK 自动重试的 HTTPX 客户端。
- 自动在 system 消息后附加 `GeneratedTests.model_json_schema(mode="validation")`，并明确要求只输出一个 JSON 对象。
- 通过 DeepSeek `POST /chat/completions` 非流式请求，关闭 thinking，启用 `response_format = {"type": "json_object"}`。
- 从响应取得内容、模型、ID、结束原因和实际用量；使用 `GeneratedTests.model_validate_json()` 做本地结构及跨字段校验。
- 只返回校验通过的生成内容；不在适配层写测试文件、执行 pytest 或构造工具实测值。

默认 `max_tokens=4096`，构造时允许 `1..32768`。DeepSeek 官方 JSON Output 要求 Prompt 同时明确要求 JSON，本实现同时使用 `response_format` 和 Schema 指令；接口定义及结束原因参见 [Chat Completions 官方文档](https://api-docs.deepseek.com/api/create-chat-completion/)。

### 5.2 超时、重试和修复预算

HTTPX 客户端的 connect/read/write/pool 超时统一取 `LLM_REQUEST_TIMEOUT_SECONDS`，不启用传输层自动重试。业务层默认预算如下：

| 预算 | 默认值 | 规则 |
|---|---:|---|
| 瞬时故障重试 | 2 次 | 只处理网络/超时、HTTP 408/409/429 和 5xx |
| 格式修复 | 1 次 | 只处理 HTTP 200 且有内容、但未通过 `GeneratedTests` 校验的输出 |
| HTTP 总尝试 | 最多 4 次 | `1 + 2 + 1`；瞬时重试和格式修复共享此硬上限 |
| 退避 | 0.25、0.5 秒起，最多 2 秒 | 指数退避；有效 `Retry-After` 优先，但同样截断到 2 秒 |

格式修复把此前输出作为 assistant 数据（最多 20,000 字符），追加一条只要求修正完整 JSON 的 user 消息，Schema 仍由原 system 消息提供。第二次仍不合法时返回 `invalid_generated_output`，不继续循环。若前序请求已经消耗总预算，修复或瞬时重试随即停止。

HTTP 400、401、402、403、404 分别归类为无效请求、认证、余额、权限和不存在错误，立即结束；429 和短暂网络/服务错误在预算内重试。HTTP 200 但外层响应无法解析、内容为空或 `finish_reason` 不是 `stop` 时归为 `invalid_response`，不把截断响应提交给格式修复。错误提供中文操作提示、分类、是否可重试、尝试次数和可选状态码，不包含响应正文、请求头、Key 或底层异常原文。

本项目未使用会自行重试的 OpenAI SDK；重试只在 `DeepSeekClient` 一层发生。这样可以从 `attempts` 直接审计实际 HTTP 尝试上限。

### 5.3 用量与安全记录

每个成功 HTTP 响应可产生一条 `LLMCallRecord`，记录用途（`generation` 或 `format_repair`）、响应 ID、响应模型、结束原因和服务返回的 `TokenUsage`。格式不合格但外层响应有效的请求也计入用量。所有调用都提供完整且自洽的 prompt/completion/total 时才计算累计用量；字段缺失或服务数字矛盾时将该条及累计用量标为 `null`，不猜测。

`safe_config` 只公开服务商、模型、地址、超时、输出及重试预算。`LLMError.safe_details()` 只公开受控错误字段。适配层没有日志调用，不保存认证头或响应正文；调用方若要保存生成结果，需要明确使用 `LLMGenerationResult`。Key 只在创建请求头时从 `SecretStr` 读取，不进入任何 Pydantic 输出结构。

源码、规格和此前工具日志会作为 Prompt 数据发送给 DeepSeek，这是产品功能所需；B3 将进一步明确数据边界和提示注入规则。B2 的真实验收仅使用固定的最小计算函数和行为文本，没有上传仓库文件或个人信息。

### 5.4 离线测试与真实验收

新增 `tests/test_llm_client.py`，18 项测试全部使用 `httpx.MockTransport`，不会访问网络或产生费用。覆盖：JSON 模式及 Schema 注入、成功解析和用量、一次格式修复、修复失败、429/5xx/网络/超时重试、`Retry-After` 截断、永久错误快速失败、空/损坏/截断响应、未知用量、总预算、配置脱敏和策略参数边界。

2026-09-26 20:46（Asia/Shanghai）通过 `python -m testgen_agent.b2_smoke` 使用本地已验证配置进行一次真实请求。该入口使用固定的轻量验证 Prompt，经正式 `DeepSeekClient` 调用并保存脱敏结果；它验证适配层，不替代 B3 的正式 Prompt。

| 项目 | 实测结果 |
|---|---|
| 服务商 / 模型 | DeepSeek / `deepseek-flash` |
| HTTP / 结束原因 | 200 / `stop` |
| 尝试 / 格式修复 | 1 / 0 |
| 响应模型 | `deepseek-flash` |
| 适配层耗时 | 1.573 秒 |
| 实际用量 | prompt 883、completion 242、total 1125 tokens |
| 结构结果 | 1 个 `calculate_total` 正常场景、非空 pytest 代码、完整场景映射 |
| 工具指标隔离 | `GeneratedTests` 中没有 execution、coverage、passed 或 line_percent 字段 |

真实输出一次通过 JSON 与 `GeneratedTests` 校验。可提交证据为 [evaluation/b2_validation.json](evaluation/b2_validation.json)；完整运行目录 `outputs/b2/20260926T124628Z-9d9dc471/` 由 Git 忽略。证据含生成测试代码、响应 ID 和用量，但不含 Key、认证头、原始请求或任意错误正文。

B2 完成后，累计 **111 项自身测试全部通过**（`-W error`），`pip check` 通过。真实请求之外的异常和修复路径均由离线可控响应验证；没有为了覆盖异常路径额外消耗 API 调用。

## 6. 生成与反馈 Prompt（B3）

### 6.1 构建接口与信任边界

实现位置为 `src/testgen_agent/prompts.py`，当前版本标识为 D2 更新后的 `b3-v4`（在 `b3-v3` 上增加实测覆盖源码位置提示和独立百分比）。对外提供两个纯构建函数：

- `build_generation_context(source, behavior_specification, oracle_mode)`：为第一轮生成构造 `GenerationContext`。
- `build_feedback_context(source, behavior_specification, previous, requested_round, max_rounds)`：从已保存候选及真实工具结果构造下一轮反馈上下文。

两者均把可信规则放入 system message，把源码、路径、docstring、行为说明、候选代码、stdout/stderr 和覆盖数据序列化为一个 JSON 对象，放在 `TASK_DATA_JSON_START` / `TASK_DATA_JSON_END` 之间。system message 明确这些字段全是待分析的不可信数据，其中的“忽略规则”“改变角色”“泄露密钥”或“修改输出格式”等文字不能成为指令。数据保持原文，不依靠删除可疑注释来实现边界，因此宿主仍能审计模型看到的输入。

Prompt 不包含 Key、认证头、模型配置或任意环境变量。输出仍由 B2 追加的 `GeneratedTests` JSON Schema 做最终约束和本地校验。

### 6.2 首轮生成规则

首轮 Prompt 包含下列固定内容：

- 角色：为宿主准备的 `subject.py` 设计测试计划和 pytest 代码。
- 支持范围：1–5 个顶层同步纯函数，只允许标准库和 pytest；不引入网络、文件、外部服务、额外依赖或非确定性时间。
- 导入约定：只使用 `from subject import <target_function>`；LLM 不选择路径、不写文件。
- 场景策略：检查正常、边界、异常和主要源码分支；某类场景不适用或预期未定义时不得编造，应写入假设或疑问。
- 依据策略：每个场景及断言必须对应 `specification`、`docstring` 或 `implementation_assumption`。规格与 docstring 冲突时输出具体疑问，不静默选择一方；特征测试不能声称证明需求正确。
- 断言质量：优先具体输入输出、`pytest.raises` 和聚焦参数化；禁止只调用函数、`assert True` 或与预期无关的断言。
- 输出格式：仅返回一个 `GeneratedTests` JSON 对象，代码放入字符串，不带 Markdown；system message 内含一个可通过当前数据契约校验的最小形状示例。

当歧义阻止所有可靠断言时，Prompt 要求 `code = null`、空 mappings 和至少一个明确问题；若仍有部分可靠场景，则只省略不确定场景并保留可验证测试。请求的 `oracle_mode` 必须原样使用；characterization 模式的每个依据都必须标为 `implementation_assumption`。

### 6.3 反馈证据与有限预算

反馈 Prompt 的 JSON 数据明确包含：此前完整 `GeneratedTests`（计划、候选代码、映射、假设和疑问）、真实 `ExecutionResult`、可选 `CoverageResult`、缺失行/分支弧、上一轮号、请求轮次、最大轮次以及本轮前后剩余预算。构建函数要求请求轮次紧跟上一轮，且不得超过 `1..3` 的预算；缺少完整候选或真实执行结果时拒绝构建，避免把猜测包装成反馈。

stdout/stderr 各保留最多 12,000 字符，同时记录 `truncated` 和原始字符数。覆盖不可用或尚未取得时写为 `null`，不猜测缺失分支。

反馈规则要求：

- 保留有规格或文档依据的有效断言；规格支持的失败可能是源码缺陷，不能把期望改成当前错误实现。
- 有证据表明测试存在语法、导入、收集或执行问题时才修复测试；对可确定预期的缺失行和分支补充聚焦场景。
- 返回完整替代候选，不返回补丁；不删除有效断言，不使用 skip/xfail、无条件通过、广泛异常捕获或修改 `subject.py` 来制造全绿。
- 日志截断、覆盖不可用或归因不清时保留问题，不伪造执行结果或覆盖率。

### 6.4 离线验证与真实请求状态

新增 `tests/test_prompts.py`，共 **21 项**离线测试。覆盖：示例符合 `GeneratedTests` 契约、七类 Prompt 内容、JSON 数据边界、中文和注入文本原样保留、characterization 模式、反馈计划/代码/失败/覆盖/预算、日志截断、覆盖缺失、无候选/无执行拒绝、非法轮次拒绝，以及正式 Prompt 通过 B2 MockTransport 后的成功解析、格式错误和认证失败受控返回。

截至 2026-09-27，累计 **159 项自身测试全部通过**（`-W error`），`pip check` 通过。`python -m testgen_agent.b3_smoke` 已改为读取公开关联样例 `examples/relationships.py` 与 `examples/relationships.md`，构造正式首轮 Prompt，调用 DeepSeek，并检查 `1.1` Schema、源码证据交叉校验、入口、确认直接关系、完整策略、单元/协作场景、oracle、正常/边界场景、导入、Python 语法和绕过模式；脱敏结果写入 `outputs/b3/<run_id>/validation.json`。

B3 的真实调用尚未执行：该调用会把上述公开关联样例源码、行为说明及正式 Prompt 发送给 DeepSeek，需要用户对这批具体数据外发作明确授权。获得授权并成功运行前，不把 B3 标记为真实 LLM 验收完成，也不创建 `evaluation/b3_validation.json`。

### 6.5 关联测试 Prompt 扩展（已实现）

`b3-v3` 已接入关系契约、C1a 图提示和策略验收：

- 任务数据的 `SourceInfo` 携带 AST 调用点、已确认边和未解析表达式，并与模型输出的 `RelationshipAnalysis` 分开。
- Agent 必须自主决定入口、函数关系和单元/协作场景，附源码或规格依据；用户无需输入调用图。
- 每个函数和关系都需给出选择或不选择理由；禁止把所有调用边机械转换为协作测试，也禁止凭名称或类型虚构数据流。
- 协作测试真实调用同文件入口和依赖；无统一入口但有明确数据流时使用有序步骤和 `step_result` 引用。预期和异常传播继续遵守 oracle 规则。
- 反馈轮保留关系、策略和历史场景，结合真实失败与缺失分支判断补充入口流程还是内部函数边界，并在证据未变化时保留关系 ID。
- Prompt 内置可通过 `1.1` Schema 的双函数直接调用示例；B2 每次调用继续动态注入最新 `GeneratedTests` Schema。

保持原有信任边界、重试预算和数据脱敏规则。离线测试覆盖未知关系、确认直接调用、独立旧样例和有序数据衔接；C1a 现已补齐多层调用、名称遮蔽、递归和真实 AST 事实到计划校验。Prompt 数据新增由确认边派生的邻接表、候选入口和递归组件，且明确它们不是业务事实。真实关联样例验收仍待明确外发授权。

## 7. 源码读取与基本 AST 检查（C1）

### 7.1 工具接口和错误边界

`src/testgen_agent/tools/source_reader.py` 提供 `read_source(path, max_bytes=128*1024)`，返回不可变的 `LoadedSource(path, code, encoding, size_bytes)`。读取前检查路径存在、是普通文件且后缀为 `.py`；文件大小先按元数据检查，实际读取时再以 `max_bytes + 1` 为界检查，避免检查与读取之间文件变化后绕过限制。`max_bytes` 必须是正整数。

编码不固定假设为 UTF-8，而是对二进制内容调用 `tokenize.detect_encoding()`，按 Python 的 UTF-8 BOM 和 PEP 263 编码声明规则解码。未知编码、声明冲突和无效字节统一形成 `SourceReadError(code="invalid_encoding")`，诊断不包含原始源码或字节。路径、类型、后缀、大小和读取失败分别保留稳定错误码，便于后续控制器决定停止而不是调用模型。

`src/testgen_agent/tools/code_analyzer.py` 提供 `analyze_source(path)`，组合读取和分析并返回 `SourceInfo`；`analyze_loaded_source()` 允许复用已读取快照。语法检查使用 `ast.parse(..., type_comments=True)`，失败形成 `SourceAnalysisError(code="syntax_error")`，携带文件、行号和列偏移，公开消息只给出行号及 `SyntaxError.msg` 的简要原因。整个流程不导入也不执行目标文件，因此模块级语句和函数体副作用不会在分析阶段发生。

错误类型保持分层：读取问题是 `SourceReadError`，语法和缺少目标函数是 `SourceAnalysisError`，有效 Python 但超出范围的是其子类 `UnsupportedSourceError`。三者都继承 `ValueError`，既便于精确处理，也允许简单调用方统一捕获输入问题。

### 7.2 提取范围

分析器只把模块体直接包含的 `FunctionDef` 作为目标，按源码顺序提取 1–5 个函数。`FunctionInfo.signature` 由 AST 规范化，保留位置参数、仅位置/仅关键字标记、可变参数、注解及默认值；同时记录清理后的 docstring 和 `def` 到函数体末尾的行号。嵌套函数不是额外目标，其条件也不并入外层函数的分支证据。

每个目标函数体内收集以下上下文，位置均来自 AST：

| AST 结构 | `SourceBranch.kind` | 保存的简短源码 |
|---|---|---|
| `if` / `elif` | `if` | 条件表达式 |
| `match` | `match` | subject 表达式 |
| `for` / `while` | `loop` | 循环头 |
| `try` / `try*` | `try` | try 入口 |
| `raise` | `raise` | 完整 raise 语句 |

所有 `import` / `from ... import ...` 会形成 `ImportInfo`，保留语句、模块、名称和行号。当前单文件范围允许标准库导入；第三方或本地非标准库模块无法在隔离工作目录中得到可靠保证，因此以外部依赖拒绝，而不是在分析时尝试安装或导入。

明显超出范围的异步函数/语法、任意相对导入、通配符导入、外部依赖和顶层类都会产生带行号、含“当前不支持”的错误。超过 5 个目标函数也会拒绝。没有目标函数时使用 `no_target_functions` 明确停止，后续控制器不得进入生成循环。

### 7.3 C1 与 C1a 的边界和验证

C1 完成时只建立安全、可复现的源码快照和基本结构上下文，当时 `call_sites`、`direct_calls`、`unresolved_calls` 保持空元组。后续 C1a 已在第 8 节实现函数调用、名称绑定/遮蔽、递归环、入口候选和有限数据传递证据；仍禁止从函数名称推断关系。

新增 `tests/test_source_analysis.py` 共 **23 项**测试，覆盖不存在路径、目录、错误后缀、大小上限、非法上限、PEP 263 中文、未知编码、语法位置、复杂签名/default/docstring/行号、主要分支和异常路径、嵌套定义隔离、标准库导入、分析不执行源码、各类超范围结构、无目标、超过 5 个目标及三个现有样例。2026-09-27 全套 **182 项**测试以 `-W error` 通过，`pip check` 无损坏依赖。

## 8. 调用关系证据与图提示（C1a）

### 8.1 调用点和保守绑定

`analyze_source()` 在 C1 结构分析后遍历每个顶层目标函数的执行体。嵌套函数、类和 lambda 的主体不归属外层调用者，因此不进入调用点；推导式则按其独立迭代变量作用域处理，首个 iterable 仍在外层作用域分析。每个 `ast.Call` 形成 `CallSite`：ID 使用 caller 和 AST 起止行列组成，另外保存完整调用表达式、起始源码行及按源码位置排列的位置/关键字/`**kwargs` 参数表达式。

确认 `DirectCall` 必须同时满足：callee 是同文件顶层目标函数；callee 以直接 `Name` 调用；该名称没有被参数、赋值、注解赋值、增量赋值、walrus、循环/with/except/match 绑定、局部导入、嵌套定义、推导式变量或删除声明为局部；模块没有额外赋值、装饰器替换或任一函数的 `global` 写入。Python 的函数局部绑定按整个作用域判断，因此即使赋值在调用之后，也不会把此前调用误判为全局函数边。

内置函数和可确认的标准库导入调用保留为未分类的 `CallSite`，不生成同文件边；C1 已拒绝第三方/相对导入。参数回调、未知名称、运行时属性、下标结果和返回 callable 等动态调用形成带受控原因的 `UnresolvedCall`。确认与未解析仍由 `SourceInfo` 契约保证互斥，Agent 不得把未解析调用升级为确认关系。

### 8.2 调用图、递归和有限数据流

`build_call_graph(source)` 从确认边派生确定顺序的邻接表并去重；`find_call_cycles(source)` 使用 Tarjan 强连通分量和显式 visited/index/stack 状态返回自递归或互递归组件，不递归展开调用链。`candidate_entry_functions(source)` 在强连通分量压缩图上选择无外部入边的根组件：普通 `checkout → calculate_total` 只提示 `checkout`，独立函数均是候选，互递归根组件可包含多个函数。该结果只表示静态图入口候选，Prompt 要求 Agent 结合规格/docstring 决定业务入口。

`find_explicit_data_flows(source)` 返回不可变 `DataFlowHint`：嵌套 `b(a(x))` 形成 `nested_call` producer/consumer 引用；直线函数体中的 `result = a(x)` 后 `b(result)` 形成 `simple_assignment` 引用和变量名。两端都必须是工具确认的同文件调用；遇到控制结构会清空简单赋值跟踪，因此不会扩展到复杂别名、容器、跨分支或隐式状态流。完整源码仍作为共享可变状态证据，动态调用另有 `UnresolvedCall`；Prompt 明确两者保持不确定，初版不实现 whole-program points-to 或状态顺序分析。

### 8.3 Prompt 与验证入口集成

首轮和反馈 Prompt 新增 `source_graph_hints`，包含确认邻接表、候选入口、递归组件、显式数据流及“不是业务入口声明”的解释。原始 `SourceInfo` 仍完整保留，提示只是确认调用事实的确定性派生，不引入第二套事实来源。B3 smoke 入口改为对 `examples/relationships.py` 调用正式 `analyze_source()`，再构造外发 Prompt，不再手工创建调用点；真实请求授权状态不因此改变。

新增 `tests/test_call_analysis.py` 共 **23 项**测试，覆盖真实关联样例、调用字段/参数、嵌套和简单赋值数据流、标准库隔离、动态调用、六类局部遮蔽、模块赋值/装饰器/global 写入、推导式作用域、嵌套定义隔离、自递归、互递归、独立函数、嵌套 callable 的唯一 ID、图接口类型检查，以及真实分析证据通过 `validate_plan_against_source()`。2026-09-27 全套 **205 项**测试以 `-W error` 通过，`pip check` 无损坏依赖。

## 9. 首轮测试计划、代码校验与候选落盘（C2）

### 9.1 一次结构化生成和接口边界

实现位置为 `src/testgen_agent/generation.py`。`generate_initial_candidate(source, behavior_specification, oracle_mode, workspace, client)` 使用 B3 `build_generation_context()` 构造上下文，并且只调用一次客户端的 `generate_tests(context)`；B2 内部为瞬时故障或格式修复发生的受控 HTTP 重试仍按其统一预算记录，不被 C2 再套一层调用循环。返回值必须是已经过 B2/Pydantic 校验的 `LLMGenerationResult`，其中一次同时包含结构化 `TestPlan` 和可选 pytest 代码。

客户端使用最小 `GenerationClient` Protocol，生产端可直接传入 `DeepSeekClient`，离线测试传入明确命名为 `SyntheticClient` 的固定契约产物。合成结果只用于验证宿主校验和文件布局，不作为真实 LLM 能力证据。没有可靠 oracle 时，合法的 `code=null`、空 mappings 和精确 questions 会作为不可执行但可审计的首轮候选保存。

### 9.2 宿主侧计划和 pytest 校验

`validate_generated_tests()` 在任何测试文件写入之前执行以下宿主规则：

- 要求 `TestPlan 1.1` 且 target_functions 与 AST 分析出的全部函数集合完全一致；调用 `validate_plan_against_source()` 验证关系引用、方向、确认边和未知调用边界。模型契约继续负责场景类型、涉及函数、关系 ID、策略决策、expected basis 和有序步骤的一致性。
- 使用 `ast.parse()` 校验测试语法；mappings 中的每个 pytest 名称必须对应一个真实模块级同步 `test_*` 函数，代码中也不得夹带未映射测试。
- 对每个映射测试，根据 scenario target 和有序 steps 核对真实目标调用；assert 必须直接包含目标调用或引用该调用的简单赋值结果，`pytest.raises` 的 body 必须调用目标。常量断言、只有调用没有 oracle、把断言藏进嵌套函数都会拒绝。
- 目标只能用无别名的 `from subject import <target_function>` 导入；禁止重新定义、参数遮蔽、赋值、推导式捕获或删除目标名称，避免实际调用被替换。
- 允许 pytest 和不涉及外部副作用的标准库；拒绝相对/第三方导入、文件/进程/网络模块、模块级执行副作用、异步测试、mock/patch/monkeypatch、skip/xfail、宽泛异常捕获、动态执行和文件修改调用。协作场景因此默认运行真实 `subject.py` 入口和依赖。

这些检查只能证明候选结构、来源引用和明显代码质量满足执行前置条件，不能证明预期值符合业务规格，也不能替代 pytest/coverage 的真实观察。失败形成带稳定 code 和可选行号的 `CandidateValidationError`。

### 9.3 固定工作区和审计快照

`stage_initial_candidate()` 只在宿主提供且尚不存在的新目录中创建以下固定布局：

```text
<workspace>/
├── subject.py
└── rounds/01/
    ├── test_subject.py       # 仅宿主校验通过且 code 非空时存在
    ├── plan.json
    ├── candidate.json
    └── llm_result.json
```

`subject.py` 由已分析的 `SourceInfo` 快照按原编码重新写出，原始源文件只读且测试核对字节未变化。模型不能提供路径或文件名。已有 workspace 立即拒绝，避免覆盖用户数据。计划和脱敏 LLM 结果总会先保存；无效语法/代码写入 `CandidateRound.validation_error`，保留原始生成内容但不创建 `test_subject.py`；有效候选的 `test_path` 保存相对路径 `rounds/01/test_subject.py`，便于后续 D/E 阶段迁移和比较。

### 9.4 样例与离线验收边界

新增 `examples/independent.py` / `.md`：`rectangle_area` 和 `is_even` 没有调用、数据传递或共享状态，离线计划只含两个 unit decisions/scenarios 和两个候选入口，不生成 relationship/collaboration。现有 `relationships` 样例使用真实 C1a call ID 构造确认关系，保存 `calculate_total` 单元场景和真实 `checkout` 协作场景；测试代码直接调用入口，不 mock 依赖。calculation、validation、discount 三个原始样例分别用正常断言、`pytest.raises` 和边界断言通过同一宿主校验。

新增 `tests/test_generation.py` 共 **31 项**，覆盖一次客户端调用、固定路径、源码字节不变、三类 JSON 往返、关系/独立策略、三个旧样例、无代码疑问、语法拒绝快照、映射/断言、导入/依赖、mock 与绕过、skip marker、计划遗漏/伪造关系、目标重绑定、嵌套函数和防覆盖。另在 pytest 临时目录用当前解释器实际执行一份标注为离线合成适配器产物的关联候选，结果为 **2 passed**；该操作不是 D 阶段执行器，也不冒充模型生成。2026-09-27 全套 **236 项**测试以 `-W error` 通过，`pip check` 无损坏依赖。

真实 B3/C2 请求仍未执行，因为会把公开 `relationships.py`、行为说明和完整 Prompt 发送给 DeepSeek，并可能产生费用；获得用户明确外发授权并成功运行前，不把 C2 记为真实 LLM 验收完成。

## 10. 独立测试执行工具（D1）

### 10.1 接口和固定工作目录

`testgen_agent.tools.run_tests(workspace, timeout=30)` 返回 `ExecutionResult`；超时参数为 `1..300` 的整数，布尔值、小数和字符串均拒绝。工作区必须已由宿主准备好 `subject.py` 和 `rounds/01/test_subject.py`，与 C2 首轮布局直接衔接。`workspace.py` 保存生成与执行共用的宿主固定路径；调用方不能传入任意测试文件、shell 命令或模型决定的输出路径。D1 初始只支持首轮；E3 已增加受控 round_number=1..3 的轮次选择。

使用当前 `sys.executable` 通过参数列表执行 `python -P -m pytest`，`shell=False`、stdin 关闭、cwd 为解析后的工作区。仅显式选择该测试文件；独立空配置、`--noconftest`、importlib 模式和禁用自动插件加载隔离父目录配置、附加测试及外部插件。固定导入路径只包含宿主包与本次工作区，支持 Windows 空格和中文路径；符号链接/junction 路径拒绝执行。此工具仅面向可信课程样例，进程及环境隔离不等同于恶意代码安全沙箱。

输入类型/超时错误抛出 `TypeError` / `ValueError`；缺少工作区、固定文件或链接越界抛出 `ExecutionWorkspaceError`；诊断目录/文件无法写入或读取抛出 `ExecutionArtifactError`。进程启动失败以及启动后的所有执行结局用 `ExecutionResult` 返回。

### 10.2 结构化观察和结局归类

宿主显式加载 `_pytest_results.py` 小型插件，记录收集项 node ID、setup/call/teardown 的 outcome、断言/pytest failure 与其他异常的区别、xfail 信息、失败位置及主要 traceback。会话开始、收集结束、每个阶段和会话结束都以临时文件加原子替换保存 JSON，超时后可读最近完整快照；统计不依赖控制台字符串。D3 补充 call 进入时的 `started_calls` 原子快照，执行数按该记录计算并校验其唯一性及收集项引用，避免挂起的 call 因没有结束报告而漏计。同时由 pytest 导出 JUnit XML 作为诊断和人工比对产物。

收集数按参数化后的测试项计，执行数只统计进入 call 的项。每个测试项只有一个最终结局：setup/teardown 错误优先归为 errors，call 断言/异常优先于清理阶段跳过，其他阶段跳过也阻止全通过；call 通过但 teardown 出错不能重复算一个通过和一个错误。普通 `assert`、`pytest.fail()` 与 `pytest.raises` 未满足属于 failed；call 中的 ValueError 等运行异常属于 errors；非严格 xfail/xpass 单独计数，严格 XPASS 按 pytest 失败项记录。完整运行必须有完整阶段记录和互斥结局，结束后再通过 B1 计数契约校验。

按真实退出码区分通过（0）、断言/执行错误（1）、收集错误/中断（2）、pytest 内部错误（3）、用法错误（4）和无测试（5）；其他退出码或不可信的结构化观察返回 `result_error`，实际退出码保留。仅有 skip/xfail/xpass、没有测试或提前退出时，`all_passed` 均为 false。启动失败的退出码为 null、计数未知。

### 10.3 超时、环境和诊断产物

测试子进程环境使用 OS 必要变量白名单；不继承 LLM Key、自定义密钥、`PYTEST_ADDOPTS`、`PYTEST_PLUGINS` 或调用方 `PYTHONPATH`。Windows 超时先对本次 PID 执行 `taskkill /T /F`（最多等待 5 秒），再确认主进程结束并回收；POSIX 使用独立会话并终止其进程组。调用方中断也结束测试进程。耗时包含启动、等待和超时清理，`timed_out` 明确表示超时；快照存在时计数表示已观测项，缺少快照时保持未知。Windows 路径及进程处理已实测，POSIX 分支尚未进行平台验收。

每次创建新的 `rounds/01/executions/run-*/`，保存 `pytest.ini`、`stdout.txt`、`stderr.txt`、`pytest_result.json`、可用的 `pytest.xml` 和 `execution.json`，诊断不会覆盖前次运行。原始 stdout/stderr 直接流入文件；返回值保留约 16K 的头尾日志并设置截断标志，stderr 补充插件记录的失败位置和主要信息。完整原始日志与结构化 traceback 可供后续回看。诊断目录位于宿主工作区内，D1 不重新写入 subject 或测试文件。

### 10.4 实测验证

2026-09-29 新增 `tests/test_test_runner.py` **40 项**检查，实际启动 pytest 覆盖全通过、断言失败、运行异常、导入/语法收集失败、空测试、参数化、setup/teardown 错误与跳过、xfail/xpass、提前返回 0、受控超时、长日志及中文空格路径、环境/配置隔离、连续运行和路径链接拒绝。启动失败及结构化记录损坏通过受控宿主注入验证；pytest 特殊退出码通过明确的 `pytest.exit` 样例验证映射，不将主动退出样例当作 pytest 自身缺陷证据。

C2 原有合成关联候选现在交给正式 `run_tests()`，工具实际观测收集、执行、通过均为 **2**。全套 **276 项**以 `-W error` 通过，编译检查和 `pip check` 通过。本阶段完成执行工具；D2 覆盖率和 D3 包含覆盖数据人工比对的整体可信度验收继续待实现。

## 11. 目标文件行/分支覆盖采集（D2）

### 11.1 共用执行器和独立数据

新增 `tools/coverage_runner.py`：`run_tests_with_coverage(workspace, timeout=30)` 返回不可变外层 `CoverageRunResult`，包含同一次运行的 `execution`、`coverage`、`artifacts` 目录和 `source_hints`；`candidate_all_passed` 直接由 execution 派生。D1 `run_tests()` 的返回接口保持兼容，两个接口共用 `_run_tests()` 的路径校验、环境、pytest 配置隔离、插件、超时和真实退出码分类；默认执行 C2 的首轮固定测试文件，E3 可显式选择后续轮次。

执行命令为当前解释器 `-P -m coverage run --rcfile=<本次配置> --data-file=<本次数据库> --branch -m pytest ...`，不 append/combine。`.coveragerc` 和 `.coverage` 位于新建的 `rounds/01/executions/run-*/`；宿主空配置不继承工程 source、exclude、fail_under 或用户 COVERAGE 环境设置。测试路径使用已校验的工作区相对路径，避免 pytest 把父目录方括号解释成参数化项。

### 11.2 精确目标过滤和指标

pytest 结束后，使用同一配置/数据路径调用 `coverage json -o <本次 coverage.json> <绝对 subject.py>`，将文件名作为明确参数而不是 glob。原始数据库可含测试/工具跟踪数据，JSON 仅导出目标；宿主 `parse_coverage_json()` 要求 branch_coverage 为 true、files 中恰好一个文件且其规范路径等于本次 `subject.py`，拒绝遗漏、额外文件及同名的其他路径。

仅读取目标 summary 的 covered_lines / num_statements 和 covered_branches / num_branches，忽略 combined percent_covered 和全局 totals。交由既有 `CoverageResult` 验证非负严格计数、缺失项唯一性及分母减覆盖数关系；行和分支百分比分别计算。分母为 0 返回 null，表示“不适用”；unavailable 指标未知，不能解释成 0 或 100。未导入目标的合法测试可得目标零覆盖；只含注释的文件可得 0 个语句和 0 个分支。

### 11.3 失败保留与源码关联

测试的 execution timeout 与导出时限独立，导出最多等待 min(timeout, 30) 秒。断言/运行/收集失败或空测试仍可导出已采集的覆盖数据；`candidate_all_passed` 及原执行结局同时保留，覆盖率达标不会掩盖失败。启动失败、测试超时或缺少本次数据库时不报告未经完成的数据。导出非零退出、启动/超时/I/O 错误、JSON 缺失/损坏/非分支或目标范围错误，均形成 unavailable 和原因，执行观察与 `execution.json` 保留。无法保存宿主结果文件时继续使用 D1 `ExecutionArtifactError`，已保存诊断不删除。

`coverage_mapper.py` 的 `build_coverage_source_hints()` 通过 AST 和源码文本把缺失行、分支两端关联到原始行文本及最内层命名函数。正数端点表示 source_line；负数端点保留原始有符号弧，并标注 code_object_exit、绝对行号锚点及对应定义行，不把负数当源文件索引。位置越界会拒绝，不填猜测片段。执行前后对读取的源码快照进行比较；源码改变或无法对应缺失位置时标记覆盖不可用。

`b3-v4` 的反馈数据新增 `coverage_source_hints`，已有原始 missing_lines / missing_branches 保留；observed_coverage 同时带宿主按计数计算的独立百分比。这些源码片段仍处于带边界的任务 JSON 内。无覆盖结果时提示为 null，采集不可用时保持错误原因与空缺失列表，不生成假缺口。

每次在 D1 产物旁保存 `.coveragerc`、本次 `.coverage`、原始 `coverage.json`、coverage_export 的完整 stdout/stderr 和结构化诊断、`coverage_result.json`、`coverage_source_hints.json` 及 `run_result.json`。联合快照明确写入 candidate_all_passed、原 execution、coverage 及提示，便于下轮和人工回看。

### 11.4 实测验收

2026-09-29 新增 `tests/test_coverage_runner.py` **37 项**：真实 coverage 子进程验证单侧分支为行 **3/4（75%）**、分支 **1/2（50%）**，联合百分比与行百分比不同；全覆盖后换单侧候选仍得到 75% / 50%，根目录旧数据库和 COVERAGE 环境配置不影响结果。覆盖失败候选、未导入目标、空分母、无分支、负数退出弧、中文空格方括号路径、超时、源码变化与实测反馈上下文。导出异常及报告损坏通过明确的受控宿主注入验证。

全套 **313 项**以 `-W error` 通过，编译检查和 `pip check` 通过；D1 40 项与已有 Prompt/C2 检查保持兼容。本阶段完成覆盖工具，D3 独立的整体可信度验收及 E 控制循环继续待完成。

## 12. 执行和覆盖工具独立可信度验收（D3）

### 12.1 人工期望与独立参考

`validation/d3/source.py` 是四行的纯函数 `classify(value)`：第 1 行定义，第 2 行判断，第 3/4 行返回非负/负数结果。人工列出的可执行语句为 `[1, 2, 3, 4]`，分支弧为 `2→3` 和 `2→4`；手写测试、覆盖期望及口径解释见 [validation/d3/README.md](validation/d3/README.md) 与 [expectations.json](validation/d3/expectations.json)。期望预先写入，不由工具运行结果反推，也不冒充 LLM 生成产物。

`d3_validation.validate_tools()` 为六类样例分别准备工具和参考工作区。工具调用正式 `run_tests_with_coverage()`；参考使用当前解释器直接执行 coverage/pytest 参数列表，不加载 Agent 结果插件，独立构造必要环境和空配置、读取 JUnit 与 coverage JSON，不调用 D2 解析器或百分比辅助函数。两条路径分别对照人工期望，检查退出码、分类、计数、独立行/分支百分比、精确执行/缺失行和弧，以及只包含 `subject.py` 的统计范围。

JUnit 把 call 阶段的 ValueError 记录为 failure，但 D1 契约区分运行错误与断言失败；导入收集错误产生一个诊断 testcase，不等于收集到一个测试项。因此期望保存两种口径并独立比对，而不把 XML 节点数机械复制为工具计数。断言失败/运行异常仍保留真实覆盖，候选不通过；空测试、异常和超时的 `all_passed` 必须为 false。

### 12.2 有界超时和计数修复

受控超时测试写入自身 PID 后睡眠 60 秒，验收默认 3 秒时限，要求两条路径均在允许的启动/清理余量内结束，并通过该 PID 的独立观察确认进程已停止。Windows 查询只申请 `SYNCHRONIZE` 权限，通过零等待判断进程句柄是否已触发，随后关闭句柄；权限不足或缺少 PID 标记不会被当作成功。[OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess)、[WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)

首轮比对发现 D1 在 call 尚未结束时记为执行 0 项，尽管 PID 标记证明该项已开始。修复 `_pytest_results.py`：在 `pytest_runtest_call` hookwrapper 进入时保存 `started_calls`，宿主校验该列表并以其长度计算执行数；未完成 call 不增加 passed/failed/errors。D3 超时样例现为 collected=1、executed=1、passed=0，覆盖 unavailable；原 D1 的“先通过一项，再超时一项”回归相应改为 executed=2、passed=1。首轮失败记录仍保留在独立的输出目录，不覆盖后续成功证据。

### 12.3 连续候选与证据保全

同一工作区连续运行全覆盖、只测试非负、只测试负数三个候选，预期独立行/分支覆盖依次为 100%/100%、75%/50%、75%/50%，缺失返回行分别为无、4、3。首轮全覆盖数据库还复制到工作区根目录作为旧数据，之后核对字节哈希不变；每次执行目录唯一，此前诊断文件的 SHA-256 全部保持不变。原始源码、候选原件及工作区副本同样核对哈希；失败记录保留关键异常信息与原始日志。

`python -m testgen_agent.d3_validation` 每次在新建的 `outputs/d3/<run_id>/` 保存命令、各工作区副本、原始 stdout/stderr、JUnit/coverage 数据、逐项 `comparison.json` 和总 `validation.json`；`--evidence` 可额外保存精选 JSON，但拒绝覆盖已有文件。退出码 0 仅在全部检查通过时返回；不符为 1，参数错误为 2。该入口只使用固定本地可信样例，无真实 API 请求；不提供安全沙箱承诺，也不扩展到 E 反馈循环。

### 12.4 实测记录

2026-09-29 09:31:40（UTC+8）在 Windows 11 / Python 3.13.9、pytest 9.1.1、coverage 7.16.1 运行六类样例与三次连续候选，全部通过；精选证据为 [evaluation/d3_validation.json](evaluation/d3_validation.json)，原始诊断根目录为 `outputs/d3/20260929T013140Z-51d68511/`。源码未改变、失败诊断保留，超时进程已结束。新增 `tests/test_d3_validation.py` **15 项**检查，全套 **328 项**以 `-W error` 通过，编译检查、`pip check` 和差异检查通过。Windows 已实测，POSIX 分支未进行平台验收。

## 13. 显式状态与动作控制器（E1）

`agent.py` 使用已有 `AgentAction` / `AgentState` 契约，新增 `ActionDecision`（动作、理由、停止原因、反馈事实）和可替换的 `AgentTools`（分析、生成、执行接口）。`run_initial_step()` 接收 `TaskInput`、生成适配器及明确的 `OracleMode`，按分析 → 模型关系/策略规划与生成 → 宿主校验 → 真实执行 → 下一步决策推进，返回 `ControllerResult`。`request.output_dir` 是新的运行工作区；`spec_path` 可读取 UTF-8/BOM 说明，显式 `behavior_specification` 优先。工具错误保留既有类型并向调用者传播；此阶段不将异常包装成最终报告。

`choose_action()` 是不调用 API 的确定性决策函数，利用已校验的模型策略与工具事实。无效候选选择修复；带疑问的候选选择人工确认并阻止执行；收集/导入错误或空测试选择检查生成测试；断言失败保留代码并选择人工确认，E1 不猜测源码责任；超时、不可恢复执行错误或覆盖不可用结束并说明原因。真实全通过且覆盖达到既有 90% 行/80% 分支目标后，还需验证所有已选协作关系都有映射场景和有效目标断言；缺少关键协作场景选择补充。跳过项或不完整结果不能达到完成条件。以上门控不等于对测试断言语义或所有规格行为的完整证明。

`build_action_context()` 只为生成、修复、补充动作准备下一次请求，不实际调用模型。未执行的无效候选携带原代码和校验错误；已执行候选沿用 B3 反馈 Prompt 的真实错误、计数、覆盖和轮次预算。额外控制器数据保留理由、已有模型策略、缺失位置所属函数及静态确认图的传递调用者链，要求模型自主判断补充内部边界或入口协作场景并说明预期依据。递归链使用已访问集合终止；未知调用不冒充确认链。执行预算耗尽时返回停止动作，禁止再构建生成上下文。

`apply_decision()` 重新验证状态契约；`ControllerResult.steps` 仅是本次调用的动作摘要，不冒充 E4 持久化轨迹。返回状态含真实执行和覆盖历史，`artifacts.candidate` 则仍为 C2 原始生成快照。E2/E3 已实现失败归因、有限修订执行、全历史记忆和最佳候选比较；双格式报告及逐步轨迹落盘留到 E4/G。当前 CLI 尚未接入控制器。

E1 新增 `tests/test_agent.py` 21 项检查：离线适配器响应配合真实 pytest/coverage 执行，验证分支只覆盖一侧时选择补充、成功首轮不自动重复请求、源码保持不变、无效候选/疑问不执行、动作与状态 JSON 往返、覆盖达标仍拒绝遗漏协作或无效断言、调用链定位、预算和停止门控、说明文件读取及工具接口替换。没有发送真实 LLM 请求，E1 不据此宣称完整多轮 Agent 已验收。

2026-10-01 Windows / Python 3.13.9 回归验证：全套 **349 项**以 `-W error` 通过（含 E1 的 21 项），`compileall`、`pip check` 和 `git diff --check` 通过。

## 14. 按失败原因选择动作（E2）

`ExecutionResult` 增加可选的 `failures` 元组，每项 `FailureObservation` 保存测试 nodeid、阶段、异常类型、原始抛出位置和 `ModuleNotFoundError.name`。字段默认空元组，旧执行快照仍可读取；成功、无测试或未启动结果不得携带失败记录。pytest 插件在 call/setup/teardown 阶段读取原始异常对象，在收集 hook 中解包 pytest `CollectError.__cause__`，不依赖 stdout/stderr 文本推断异常类型。结构化记录无效时沿用 D1 的 `result_error` 保守回退。

`failure_analysis.classify_failures()` 根据原始异常来源分类：测试文件中的 ImportError/NameError/SyntaxError 或错误 subject 导入属于生成问题，可在预算内修复；缺失其他模块或候选校验发现第三方依赖则报告环境/不支持问题，禁止自动安装。源码中发生的名称/运行异常不擅自归因给测试。没有结构化异常的旧失败记录默认需确认，尤其收集失败不再默认进入修复。`ActionDecision.status` 对疑似缺陷和不确定失败返回 `needs_review`，环境终止、预算或无进展结束则根据已有可运行候选区分 `failed` / `partial`。`issues` 包含具体位置及规格证据，应用决策时追加到 `AgentState.issues` 并避免重复，保留原候选和执行数据。

明确规格支持的自动核验采用有限且可解释的规则：当前仅支持单目标函数、单个场景映射、单参数字面量直接调用的相等断言；测试函数体只有该断言，失败位置必须对应此断言，调用输入还要匹配计划中的场景输入。宿主从原始行为说明或 docstring 中读取标题为“输入/预期”或“input/expected”的两列表格，实际输入对应的所有可解析预期必须一致并与断言字面量及类型相同。只有模型标记 `expected_basis=specification` 不足以证明断言正确。冲突表格、未定义输入、映射错误、特征测试、参数化、异常 oracle、一般自然语言或多函数协作预期不满足该核验规则时均返回人工确认；此有限检查不是通用语义证明，也不保证识别任意自然语言冲突。

核验支持的实际失败产生 `suspected_source_defect` 和规格行引用，选择 `request_review` / `suspected_source_defect`，保留失败用例和原预期，不构建后续修复请求。无法确认时选择 `request_review` / `ambiguous_specification`，不声称已确认 Bug。超时直接停止；相邻候选代码及校验错误或实测计数/覆盖缺口相同，且仍需修复或补充时，以 `no_progress` 停止；已经通过完成门控的重复候选仍可正常完成。此检查不以新工作区路径、时间或日志变化作为进展。E3 已进一步接入有限多轮执行、历史总结、AST 重复检查和无覆盖提升停止。

2026-10-01 新增 `tests/test_failure_analysis.py` 29 项检查。真实 pytest 执行折扣样例的 `calculate_discount(100) == 90` 返回断言失败并定位到第 4 行，宿主读取明确规格表格后报告疑似缺陷，原源码及断言 90 保留；适配器只被请求一次。真实收集/执行验证还覆盖不存在的外部模块、错误函数导入和测试名称错误。其余检查覆盖冲突/不足依据、docstring 表格冲突、特征模式、场景输入与位置不一致、预算和重复无进展门控、问题保存及兼容旧执行结果。仅用离线合成模型响应，无真实 LLM 请求，不把这些结果称为完整多轮 Agent 验收。

E2 最终回归：Windows / Python 3.13.9，全套 **378 项**以 `-W error` 通过，`compileall`、`pip check` 和 `git diff --check` 通过。

## 15. 任务记忆与有限反馈执行（E3）

### 15.1 控制循环与每轮快照

`run_agent(request, client=..., oracle_mode=..., tools=...)` 接通 E1/E2 的确定性动作门控。`request.output_dir` 必须是全新的工作区，已存在时在模型请求之前拒绝覆盖。最多生成 3 个候选（含无效候选），有效候选才执行；配置可缩短到 1/2 轮。C2 初始接口保留，修订由 `stage_revision_candidate()` 写到 `rounds/02` / `03`，固定目标名和源码由宿主提供。D1/D2 增加 `round_number=1` 关键字，显式选定一轮测试与诊断目录，默认兼容旧首轮调用；不递归执行历史轮次。每轮仍使用独立 coverage 数据库，仅统计原目标。修订前检查工作区源码与原任务快照一致；若宿主副本发生变化，则停止并在结束导出时保留变化后的 `subject_at_stop.py`，将宿主 `subject.py` 恢复为原始任务快照，保证导出的旧候选对应原源码；不写回用户输入文件。

输入、模型和执行工具的可恢复性由既有模块处理；循环不叠加额外 API 重试。现有适配器每次最多 4 个 HTTP 请求，最多 3 次生成请求，共最多 12 次 HTTP 尝试；候选预算与重试预算分开。结果 `attempts` 及失败 `LLMError.attempts` 用于计数。实际 token 用量可累计，任一轮缺失用量则总量保持未知，不将未知填成 0。不可恢复模型/输入/工具错误会终止，保留历史可用候选，并输出实际错误类型或工具安全诊断；最终结果落盘失败向调用者抛出，不声称已保存。

### 15.2 任务内记忆和有效测试保护

`AgentState` 保留原始源码、编码和行为说明、每轮完整 `GeneratedTests`、原执行结果、覆盖、问题和最佳候选。`build_action_context()` 在 B3 的上一轮反馈之外增加所有历史轮次的计划、关系、策略、场景、错误/失败位置、覆盖缺口、当前问题、受保护测试名称及剩余预算；不重复发送所有完整日志，但原日志仍在每轮目录。所有记忆只属于本次状态对象和工作区，不使用全局任务缓存、向量库或跨用户数据。初始无效候选的修复上下文也包含旧代码、校验错误和预算。

宿主从真实执行的已通过项确定受保护测试：全通过候选保护全部测试；含断言/运行错误的完整结果可以依据结构化失败节点排除失败函数，保留其余明确通过的函数；无失败细节的旧计数快照不猜测单项通过身份。保留旧函数 AST（含断言、装饰器）、场景映射、输入/预期依据及关联证据，并保持原导入、字面量常量和辅助函数，禁止通过重复绑定间接改写断言。补覆盖须增加新的测试函数；宿主不尝试证明任意断言重写等价。这是一项有意保守的限制，合法但改写旧函数的候选也可能被拒绝。

校验拒绝的候选保留模型原产物和错误，不写为可执行测试。状态/最终报告契约允许 `validation_error` 非空的拒绝候选保存与宿主事实不符的原计划作为审计数据；只有通过校验的候选才须满足原 oracle/schema/源码事实交叉约束，执行仍禁止带校验错误的候选。生成接口同时验证原始 oracle 模式，不允许通过更改任务模式规避规格失败。成功修复并执行全通过后，旧生成错误从未解决问题中移除，但原错误仍在历史和落盘快照中。

### 15.3 停止与最佳候选

除 E2 的缺陷、疑问、超时和环境门控外，AST 与任一历史有效候选重复（包括只改注释/格式）时，在再次执行前以 `no_progress` 停止；新候选代码虽不同，若尚未达标且行/分支覆盖均未高于此前已通过候选，也以 `no_progress` 停止。完成门控仍要求关键协作场景有效，覆盖不是质量保证。最多 3 轮的硬上限在状态契约和循环范围两处生效。

`select_best_candidate()` 只选择 `CandidateRound.available` 的历史候选。按全通过优先、达到覆盖目标优先、覆盖可用优先、分支覆盖/行覆盖/通过数依次比较，同分取较早轮；这避免仅因某一覆盖指标更高而选回未达标的旧候选。修订代码无效或后续 API 失败不会抹掉之前的可用候选。若追加测试揭示疑似缺陷，整体仍为 `needs_review`，失败轮次、原断言和规格证据保留；导出的候选可选此前全通过版本，但不能丢掉失败证据。

### 15.4 结束摘要与验收

返回 `AgentRunResult`，含最终状态、真实动作/理由、内存动作摘要、最终测试路径及状态/摘要路径。每轮更新 `candidate.json` 和 `state.json`；结束写 `summary.json` 的状态、真实停止原因、选中轮次、候选/执行轮数、HTTP 尝试及实测用量、未解决问题，并将选中测试导出到工作区根目录 `test_subject.py`。无可用候选则不伪造最终测试。此摘要实现 E3 的停止原因输出，但不是 G 的 `FinalReport` 双格式展示；E4 的逐步 `trace.jsonl` 已在第 16 节接入，CLI 尚未接入。

E3 新增 `tests/test_agent_loop.py` 34 项验证。离线模型序列配合真实 pytest/coverage，三轮依次补正数、零值、负数分支达到 100% 分支覆盖；验证预算耗尽、无效追加保留旧候选、修复后补齐、保护已通过函数/场景/常量/依赖、局部运行错误中的已通过测试保护、重复代码与无覆盖提升停止、失败缺陷证据保留、API 错误与计数、未知用量、任务隔离、原源码和历史快照不被覆盖。没有发送真实 LLM 请求，结论仅覆盖离线适配器和真实本地工具的多轮集成。

E3 最终回归：Windows / Python 3.13.9，全套 **412 项**以 `-W error` 通过（E3 新增 34 项），`compileall`、`pip check`、`git diff --check` 通过。

## 16. 可追踪运行与逐步轨迹（E4）

### 16.1 事件契约和增量落盘

`tracing.py` 定义 `TraceEvent`：事件 Schema 版本、独立 run_id、连续序号、UTC 时间、轮次、状态摘要、工具名、动作、输入摘要、结果摘要和简短理由。事件阶段为 `run_started`、`tool_started`、`tool_finished`、`tool_failed`、`decision`、`run_finished`。无工具的控制器决策使用空工具名；轮次 0 表示输入分析或尚未取得首轮候选。工具调用明确记录待执行的轮次，不把模型尚未返回的内容冒充已执行候选。工具完成后的控制决策记录缺失函数、问题类型、下一步动作和停止原因，无模型内部推理过程。

`TraceWriter` 排他创建新工作区、`run.json` 与 `trace.jsonl`，每项事件单独追加、flush、fsync，运行中即可读取已有完整 JSON 行。`run_agent()` 使用 UUID 作为运行标识，工作区仍使用调用者指定的新目录；任何已存在目录都在请求前拒绝覆盖。首轮 C2 落盘新增 `prepared_run_id` 接口，只接受包含 `run.json` / `trace.jsonl` 且 ID 一致的预创建工作区，仍拒绝既有候选或其他文件；普通 C2 调用继续要求全新目录，不开放一般覆盖开关。

工具开始事件在调用前写入，因此首轮模型故障也保留证据。工具异常记录错误类型，随后已有控制器保存停止决策；导出错误保留 `export_results` 的失败事件并向调用者抛出。轨迹自身写入失败使用 `TraceArtifactError` 直接抛出，不递归尝试记录相同错误、不返回伪造成功结果。若进程中断或最终日志落盘失败，事件前缀可能以开始/决策事件结束，缺少 `run_finished` 的日志不能视为完整结束轨迹；多文件产物不承诺原子事务提交。

### 16.2 模型配置、次数和用量来源

`run.json` 保存公开 `TaskInput`、oracle 模式和已知适配器公开配置。实际 DeepSeek 客户端采用既有 `safe_config`（模型、服务地址、超时、输出 token 和重试/格式修复预算），其他替代适配器只记录类型，未知重试策略保持 `null`，不猜测其配置。请求中声明的模型与实际返回模型分别记录，可用于发现配置不一致。

`ObservedGenerationClient` 包装统一生成接口，记录模型请求开始、返回或失败，输入只记录上下文长度。返回记录适配器报告的 attempts、format_repairs、latency、requested/response model 和各已返回 completion 的 purpose/finish/usage；不把成功响应条数当作全部 HTTP 尝试数。暂态故障的尝试数由适配器 attempts 汇总，失败采用 `LLMError.attempts`，不复制原始响应正文。累计计数由观察包装器统一提供，即使首轮模型已返回但落盘失败也能保留。HTTP 尝试的来源显式标为 adapter_reported；手写离线适配器报告的模拟次数不冒充真实网络请求，验收入口另标实际网络数为 0。用量未知或任一轮缺失时保持 `null`，不从字符数估算 token。

### 16.3 文件引用与完整运行结果

轨迹记录分析函数/关系数量、候选校验和映射数、每轮 plan/candidate/LLM 快照位置，以及执行种类、真实计数、覆盖状态/百分比和执行诊断目录。代码、完整工具日志和原始 coverage JSON 保留于 E3 各轮路径，轨迹只保存摘要与引用。`export_results` 单独记录开始/返回/失败；`run_finished` 汇总最终状态、真实理由、选中轮次、请求计数/用量和输出路径。`AgentRunResult` 增加 `trace_file` / `metadata_file`，`summary.json` 同样保存这两个引用。原 `run_initial_step()` 仍是单步开发接口，完整 E4 轨迹由 `run_agent()` 提供。G 的 Markdown/JSON `FinalReport` 尚待集成。

### 16.4 离线复现与实测

`python -m testgen_agent.e4_validation` 在新的 `outputs/e4/<UUID>/` 下创建反馈/缺陷两个独立运行。反馈使用 `validation/e4/source.py` 和手写候选，首轮正数 → 补零值 → 补负数，真实覆盖反馈触发 `add_missing_cases` 后达到目标；缺陷使用公开 discount 源码/规格和输入 100、预期 90 的断言，真实失败触发 `request_review` / `suspected_source_defect`，一轮停止并保留测试。入口逐项核验来源文件不变、轮次/停止原因、连续事件、最终事件和原始测试/coverage 产物。`--output` 可更换输出根目录，不读取 API 配置、不发送请求。

2026-10-01 验收全部通过：反馈轨迹 **38** 项事件、三轮完成；缺陷轨迹 **16** 项事件、一轮后 `needs_review`。原始工作区为 `outputs/e4/8410b3d559774f7d95488bf47fe2f04e/`；提交用精选摘要、两份完整轨迹和公开配置保存在 `evaluation/e4_*`。所有模型响应均为手写合成数据，工具执行和覆盖结果来自真实本地进程，真实网络请求数明确为 **0**。

`tests/test_tracing.py` 新增 **14 项**检查：真实反馈/失败轨迹、初始 API 故障、模型已返回后落盘失败的计数、首次请求前日志已存在、MockTransport 格式修复/公开配置/脱敏、UUID 隔离与拒绝覆盖、真实追加 I/O 失败、导出失败、预创建工作区保护、说明文件失败、相对目录和离线验收入口。没有执行真实 LLM 多轮验收。

E4 最终回归：Windows / Python 3.13.9，全套 **426 项**以 `-W error` 通过（新增 14 项）；`compileall`、`pip check`、`git diff --check` 通过。

## 17. 自身测试与真实端到端验收（F1）

F1 复用此前各阶段的关键逻辑测试，并增加 `test_f1_acceptance.py` 14 项集成检查。多层调用按 caller/callee、源码行和表达式核对；协作候选仅直接调用入口，真实覆盖证明依赖函数执行，数据衔接、异常类型和漏抛异常的错误变体均被同样断言识别。mock 只替换模型响应，不替换源码依赖或执行工具；关系/策略按契约与引用核验，不要求模型理由使用固定措辞。

`f1_validation.check_saved_run()` 将实际 Agent 状态构造成已有 `FinalReport`，核对每轮候选、状态文件、结束摘要、选中导出代码、终止事件及原始执行/覆盖产物。第二轮失败不覆盖第一轮可用测试，报告保留失败轮次、原断言及需确认问题；选中旧测试的 all_passed 与任务整体 needs_review 可以同时成立，不能据此升级 completed。篡改状态/摘要/导出代码/结束轨迹会被检查发现。这里只验证报告契约与事实一致性，不实现 G2 展示。

`python -m testgen_agent.f1_validation --live` 只发送固定计算/协作课程样例及正式 Prompt，每项最多两轮、每轮一次暂态重试/一次格式修复、4096 输出 tokens。自动测试将该入口替换为手写客户端或 MockTransport，不需要 Key 或外部网络；缺 Key 在创建客户端前保存配置失败，503 后成功的模拟链路核验实际尝试数为 2、候选轮次为 1。运行目录为独立 `outputs/f1/<UUID>/`，`--output` 可替换根目录。

2026-10-03 真实调用首先发现 `b3-v4` 的“未定义类别可写 assumptions 或 questions”规则与控制器的阻塞 questions 门控不一致。计算和协作两项响应均将明确范围限制写为问题，真实状态为 needs_review，未执行测试；用量合计 11,563 tokens。这不是去掉问题字段后执行成功的证据，原响应/状态均保留。修订 `b3-v5` 明确将已排除输入或不适用类别归入 assumptions，真正冲突和不确定预期仍写 questions 并停止；控制器未放松门控。

修订后两项各一轮、一次真实 HTTP 请求完成：计算 6 条测试全通过，目标行 2/2；协作 4 条测试全通过，目标行 4/4；均无分支，分支覆盖为 null。使用 deepseek-flash，成功批次实测 11,311 tokens、各耗时约 12 秒。执行/代码/覆盖来自实际模型响应与本地工具，原文件未改，所有验收检查通过。网络不可达批次失败同样保留，HTTP 尝试不能解释为远端已收到请求，未知用量不估算。精选摘要和复制文件映射为 `evaluation/f1_validation.json`，完整选定产物位于 `evaluation/f1/passed/` 与 `pre_fix/`；仅保留公开数据，不含密钥或认证头。复现与测试映射见 `validation/f1/README.md`。

两项真实验收覆盖正确实现的单轮集成；未宣称真实多轮效果、缺陷检出率或广泛模型可靠性。F2 评测集见第 18 节，F3/F4、G 的 CLI/报告展示仍按后续阶段实施。

F1 回归：初次全套 439 项以 `-W error` 通过；最终 F1/Prompt 35 项以同参数通过（包括全部 14 项新增 F1 检查），新增多层调用检查后当前共 440 项。`compileall`、`pip check`、`git diff --check` 通过。最终真实运行再次核对候选、状态、摘要、选中代码和终止事件，全部一致，结果保存在 `evaluation/f1/final_audit.json`。

## 18. 冻结小型评测集（F2）

新增 `benchmarks/f2/v1/`，8 个任务、12 个顶层同步纯函数。四类各 3 个：数字边界（subtotal/clamp_int/score_band）、字符串（normalize_labels/format_labels/initials）、列表（compact_runs/safe_mean/rotate_left）、异常与多分支（validate_quantity/order_total/classify_packet）。开发 4 个任务含 8 函数，留出 4 个单函数任务各占一类。所有案例为新增手写样例，不扩展既有演示案例以迎合当前 Prompt。

同文件订单链是 order_total→validate_quantity/subtotal，明确校验返回值进入计价及异常传播；标签链是 format_labels→normalize_labels，明确去空、规范化、顺序与重复值进入展示。独立对照的 clamp_int/compact_runs 没有确认边和组合规格。标注存于独立 annotations 文件，含确认边的行/表达式、合理入口、关键组合行为的手写场景引用；不会把无法绑定的字符串/列表方法升级为确认边。

源码的相邻公开规格给出输入域、值/异常及副作用约定。oracles 中 69 条手写字面量预期在执行前确定，不由参考实现生成答案；同时核验返回类型、输入不变和需要的新列表。留出集仅在本地校验参考实现和预期，F2 不调用模型、不改 b3-v5；F3 必须先冻结开发集所选设置，再评测留出集，不能依据留出结果调 Prompt。

6 个已知错误版本分别影响 validate_quantity/order_total/normalize_labels/safe_mean/score_band/rotate_left，每份完整源码仅改变一个声明函数。订单入口多传一件数量破坏函数间数据衔接，保留组件单元行为正确；数量 0 错误接受破坏入口异常传播。其他覆盖遗漏大小写转换、遗漏空列表分支、80 分边界和错误旋转方向。每个变体有手写见证与允许的失败异常类型；这不是自动变异测试框架。

`benchmark.py` 定义版本化 manifest、案例、预期和标注契约，验证四类/划分/目标一致性及 38 份文件的 SHA256。`public_input()` 仅返回 SourceInfo 和公开说明，模型上下文不含隐藏预期/标注/错误描述。测试验证三类开发任务的 Prompt 不泄露手写场景/变体 ID。F3 的工具可显式读取评测元数据，生成路径仍只使用源码/规格。

`f2_validation.py` 排他创建 UUID 工作区，先核验每个参考实现的真实 pytest/coverage 与全部手写预期、关系位置，再将字节相同的手写测试交给相应错误版本。只接受指定 witness 的真实 call 失败及已声明异常，不把语法/导入/环境问题作为错误可用证据；末尾重新核对全部文件指纹。原测试/源码/命令/日志/XML/coverage 原始 JSON 与结构化结果分别保存，覆盖只统计各 subject.py，不混入 Agent 文件。该工具不调用控制器或模型，不生成或评价 LLM 测试。

2026-10-03 实测全部通过：8 个参考任务 69 项预期全通过；6 个变体分别产生 2/1/4/1/1/3 个错误见证，其中 mean 为空输入导致的目标内 ZeroDivisionError，其余为断言失败。数据衔接版本组件单元全通过、入口协作见证失败。参考任务目标行全部覆盖，有分支任务也覆盖全部分支；initials 无分支显示不适用。这些覆盖率来自手写参考检查，不能写作 Agent 生成测试覆盖率。精选证据 `evaluation/f2_validation.json` 及 `evaluation/f2/`，完整任务表与复现入口见 `benchmarks/f2/v1/README.md`。F3/F4 的对照、检出实验仍待执行。

F2 新增 23 项自身检查；配合源码与关系回归共 69 项以 `-W error` 通过，最终 F2 专项 23 项再次通过，含错误返回类型、列表别名及输入修改的预期检查。当前测试集共 463 项，未宣称本阶段重跑全套。`compileall`、`pip check`、`git diff --check` 通过；自动验证命令/结果见 `evaluation/f2_tests.json`。

## 19. 共享首轮的对照与已知缺陷评测（F3/F4 工具）

`experiment.py` 在模型调用前冻结 F2 manifest、案例顺序/划分、Prompt b3-v5、生成模块 SHA256、适配配置和预算。每任务实际请求一次首轮；`SharedSeedClient` 核对两方案首次 GenerationContext 完全相同，再重放同一结果或错误。基线 max_rounds=1，反馈 max_rounds=3；后续请求经过原控制器与测试保护规则，不改 Prompt、不利用留出结果调参数。每轮真实 pytest/coverage、模型结果和 trace 都保存。

各方案比较成本包括一次首轮的次数、token 与生成耗时，以及本方案实际增加的调用和控制器耗时。实际总成本只计共享首轮一次，避免把两方案相加误写成网络成本。响应用量未知保持 null；合成适配器结果明确标记 offline_fixture，实际网络次数为 0。汇总含开发/留出分表、可运行/全通过/完成任务数及分母、选中轮次、有效测试数、覆盖与不可用/N/A 数量，逐案例记录无改善、下降和失败。

F4 首先要求最佳候选在正确实现上全部通过，并以相同测试独立复测参考实现。错误版本保留测试字节，AST 核对只有 manifest 指定函数发生变化。检出需是真实 call 阶段、符合预设缺陷异常类型、映射场景调用目标函数或经已确认边到达它；源内异常还需位于变更函数行区间。导入/收集/环境错误、测试字节变化和参考复测失败均不得计入检出。无法归因的失败单列，而目标实现空分支 ZeroDivisionError 可以在证据满足时计入。

`rebuild` 仅从保存的 manifest、状态、成本、执行结果、源码和测试计算表格，不依赖原数据目录、原执行路径或模型连接。它核验公开输入及评测标注指纹、种子一致性、导出候选/状态/成本一致性、正确复测与错误版本三方测试字节及源码指纹。`archive` 复制原始日志/XML/coverage JSON 和可重建输入，排除缓存/数据库，输出各文件 SHA256 与大小，拒绝覆盖或嵌套归档；保留原始路径仅作诊断而不跟随读取。

离线流程检查用手写合成首轮及追加响应驱动真实本地 pytest/coverage，验证分支补充、首轮共享成本、源内运行缺陷归因、导入错误排除、无映射失败排除、证据篡改拒绝、未知指标分母和便携归档重建。此类合成输出不代表真实模型效果。

2026-10-03 真实 F3/F4 命令被自动审批拒绝：源码/规格发送至 DeepSeek 的具体外部目的地授权尚不明确。已请求授权，当前不填写真实对照结果或标记 F3/F4 全部验收完成。获得授权后使用冻结设置运行 8 个任务，并对订单/标签的组合断言及独立函数策略逐项复核；不得按结果挑选案例或隐去无提升案例。

## 20. 后续设计章节

真实实验结果、CLI 与报告交付随对应阶段补充。没有实际验证的内容不得填写为已实现或实测结果。
