# 测试生成 Agent 技术设计

> 当前进度：A1、A2、A3 已完成。当前提供配置检查 CLI、DeepSeek HTTP 客户端及可复现的 A3 验证入口；真实最小 API 请求、手写样例 pytest 和覆盖率 JSON 已验证。尚未实现测试生成、通用执行工具或 Agent 反馈循环；本文其余任务接口、状态和输出目录仍是后续实现约定。手写样例测试不是模型生成结果。

## 1. 范围与验收（A1）

### 1.1 产品目标与边界

输入一个小型 Python 源码文件及可选行为说明，Agent 生成 pytest 测试，实际执行测试，读取失败和覆盖率反馈，在有限轮次内修复生成错误或补充场景，最后保存测试、报告和运行轨迹。

- 初版处理单个 `.py` 文件中的 1–5 个顶层同步纯函数，覆盖数字计算、字符串、列表和输入校验。
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
| 3. `completed` | 有可用最终候选，全部通过且无绕过，目标范围覆盖达到上述阈值，无未解决错误或疑问，必要报告与轨迹成功保存 | 生成、执行、覆盖和交付均完成；特征测试模式仍必须明确标记其结论范围。 |
| 4. `partial` | 有可用候选、没有待人工复核的行为问题，但未满足 `completed` 的某项要求 | 全通过但覆盖不足/不可用，达到轮次上限、无进展，或后续 API/执行/报告错误导致未完成。保留上一轮可用候选并说明限制。 |

人工复核证据不会因后续 API 或覆盖率错误被降格成普通执行错误；报告同时列出这些错误。否则，不可恢复错误发生后是否存在历史可用候选，决定 `partial` 或 `failed`。

最终候选必须来自某个保存的轮次，并记录轮次号。对 `needs_review` 保留与复核问题相关的候选和证据；不能只展示此前通过的版本来掩盖有效失败。追加候选无效时可退回历史可用候选，但当前失败快照和未解决问题仍须出现在报告中。候选排序的具体实现留到 E 阶段。

停止原因另行记录，不与最终状态混用，例如 `coverage_target_met`、`round_limit_reached`、`no_progress`、`suspected_source_defect`、`ambiguous_specification`、`execution_timeout`、`unrecoverable_error`。达到预算上限不会自动变成 `completed`。

### 1.6 三个最小样例

样例源码和行为说明一一对应，docstring 与说明保持一致。均只使用标准 Python、无外部依赖、无文件或网络副作用。

| 类型 | 源码 / 说明 | 人工核验的关键预期 | 后续 Agent 验收目标 |
|---|---|---|---|
| 正常计算 | `examples/calculation.py` / `examples/calculation.md` | `calculate_total(12, 3) == 36`；`(0, 5)`、`(12, 0)` 都为 0 | 非空有效测试可运行，正常与零值边界通过；目标行覆盖达标，分支不适用。 |
| 多分支校验 | `examples/validation.py` / `examples/validation.md` | 0/59 为 `fail`，60/89 为 `pass`，90/100 为 `excellent`；-1/101 抛 `ValueError`，浮点/字符串/布尔值抛 `TypeError` | 覆盖类别边界和类型/范围错误。若首轮遗漏分支，反馈应引导追加；不能保证模型首轮一定遗漏。 |
| 明确规格下的缺陷 | `examples/discount.py` / `examples/discount.md` | 99 → 99，100 → **90**，101 → 90；源码在 100 时实际返回 **100** | 生成规格支持的断言，实际执行发现阈值错误，进入 `needs_review`，保留断言和疑似缺陷证据。 |

计算样例的非负整数输入域是前置条件，域外行为未定义；不要求自动生成不存在的输入校验。校验样例明确排除 `bool`。折扣样例约定向下取整，避免浮点或金额舍入歧义。

说明文件中公开的输入输出是任务规格及人工核验锚点；后续评测的隐藏参考测试和错误变体答案不能混入模型输入。缺陷样例只展示一次确定的边界错误，不代表 Agent 已具备自动缺陷检出能力。

### 1.7 A1 验收记录

- 已固定六类输入、默认值和非法输入处理。
- 已固定最终测试、双格式报告、轨迹及每轮快照的输出约定。
- 已分开生成、可运行、全部通过与覆盖充分四个维度，并定义四个最终状态及判定优先级。
- 已准备三个源码文件和三个 UTF-8 行为说明，覆盖正常计算、多分支校验和明确规格缺陷。
- 2026-09-26 使用本地 Python 3.13.9 做三个源码文件的语法/导入检查及 32 项行为核验（含整数子类、异常类型和已知缺陷确认）：正常计算与校验符合规格；折扣的 100 边界确实得到 100，违反预期 90。该偏差为有意保留的课程样例。核验前后源码 SHA-256 一致，未产生缓存或修改源码。

本记录不替代 A3 的真实 API、样例 pytest 和 coverage 验收；A2 的工程环境和依赖验收见第 2 节。

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
│   ├── models.py / prompts.py / agent.py / reporting.py
│   └── tools/
│       ├── __init__.py
│       ├── source_reader.py / code_analyzer.py / test_runner.py
├── tests/test_config.py
├── examples/                  # A1 的三个样例及说明
└── evaluation/                # 后续评测目录
```

- `python -m testgen_agent` 和安装后的 `testgen-agent` 使用同一个 CLI 入口；当前实现 `--help`、`--version`、`--check-config` 及配置覆盖参数。
- `config.py` 完成配置读取、校验与脱敏摘要，`llm_client.py` 提供配置驱动的 HTTP 客户端工厂；客户端创建不会发送请求。
- `models`、`prompts`、`agent`、`reporting` 及源码/执行工具模块当前只有注明对应阶段的骨架，不包含模拟成功的业务实现。
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

`request_timeout_seconds` 当前设置 HTTPX 的连接、读、写及连接池等待超时，不表示整个响应的总墙钟时限；`execution_timeout_seconds` 将在 D 阶段用于测试子进程的总执行时限，两者不混用。

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

阶段 A 的范围、环境和真实 API/工具验证已完成。B1 数据结构、B2 LLM 生成适配、B3 Prompt 以及后续 Agent 流程仍未实现；本次没有勾选后续业务功能。

## 4. 后续设计章节

模块架构、数据结构、Prompt、工具接口、重试预算、反馈决策与实验结果将随对应阶段补充，均写入本文件。没有实际验证的内容不得填写为已实现或实测结果。
