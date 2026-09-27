# 测试生成 Agent

课程项目：为单个 Python 文件中的 1–5 个顶层同步纯函数生成并执行 pytest 测试集。设计目标是由 Agent 自动分析函数关系，决定单元测试和协作测试策略，再根据失败及覆盖率反馈进行有限迭代。LLM 服务商选用 DeepSeek。

当前完成 A1/A2/A3/B1/B2，以及 B1 关系契约扩展和 B3 `b3-v2` 生成/反馈 Prompt 的离线验证：包括输入输出及状态设计、四组源码/行为说明样例、工程骨架、配置检查、DeepSeek 结构化生成适配、手写 pytest/coverage 环境验证、兼容旧产物的数据模型和正式 Prompt 构建。B3 真实请求尚待明确授权发送公开关联样例数据；AST 自动关系分析、测试执行和反馈循环尚未实现。设计与验收记录见 [Design.md](Design.md)，进度见 [TASK_CHECKLIST.md](TASK_CHECKLIST.md)。

2026-09-27 新增范围：自动判断同文件函数关系，并自主规划测试集。所需 `1.1` 数据契约和 `b3-v2` Prompt 已实现；AST 事实提取、端到端生成/执行与报告仍未实现。修订任务预算为 58 小时。

## 函数关系与测试集

用户只需提供源码和必要的行为说明，无需手动列出函数关系或指定测试类型。当前契约可保存 AST 工具的调用点、确认边和未知调用，并校验 Agent 给出的关系、入口及测试策略；实际 AST 提取工具在 C1a 实现。

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

当前没有 `--source` / `--spec` 运行接口；任务清单中的端到端命令仍是后续设计，不是已实现命令。`models.py` 已实现 B1 数据契约，`llm_client.py` 已实现 B2 DeepSeek 适配层，`prompts.py` 已实现 B3 首轮与反馈上下文；`agent`、`reporting` 和源码/执行工具模块仍是注明阶段的骨架。

`models.py` 提供 `SourceInfo`、`RelationshipAnalysis`、`TestPlan`、`GeneratedTests`、`ExecutionResult`、`CoverageResult`、`AgentState`、`FinalReport` 及辅助类型。关系 Schema `1.1` 保存调用证据、入口、逐函数/关系策略、unit/collaboration 场景和有序数据传递；旧 `1.0` 单函数产物仍可读取。生成内容与工具实测结果分开；百分比和报告指标由计数及选定候选计算，未知值使用 `null`。接口、状态引用和序列化约定见 Design 第 4 节。

`llm_client.py` 提供 `DeepSeekClient.generate_tests(context)`：自动附加生成结果 Schema，使用 DeepSeek JSON Output，再用本地 Pydantic 严格校验。默认对瞬时故障最多重试 2 次，对格式错误最多修复 1 次，总 HTTP 请求不超过 4 次；400/401/402/403/404 立即失败。错误和公开配置不包含 Key、认证头或响应正文。B2 设计与实测见 Design 第 5 节。

```powershell
# 发送一次真实的固定 B2 结构化生成验证；可能产生 API 费用
.\.venv\Scripts\python.exe -m testgen_agent.b2_smoke
```

每次结果保存到 `outputs/b2/<run_id>/validation.json`。2026-09-26 实测 `deepseek-flash` 一次返回合法结构，耗时 1.573 秒、1125 tokens，无格式修复；精选证据为 [B2 验证结果](evaluation/b2_validation.json)。此命令使用固定轻量验证 Prompt，不等同于后续 B3 的正式 Prompt 或端到端 Agent。

`prompts.py` 的 `b3-v2` 把可信规则放入 system message，把源码、调用事实、行为说明、候选和工具日志放入带边界标记的 JSON 数据。首轮要求 Agent 自主选择入口、关系和单元/协作策略，同时覆盖正常/边界/异常/分支场景及逐项预期依据；反馈轮携带此前关系、策略、候选、真实失败、缺失覆盖和剩余预算，并禁止删除有效断言、skip/xfail、广泛捕获异常或修改源码。

```powershell
# 向 DeepSeek 发送公开 relationships 样例源码、行为说明及正式 B3 Prompt；可能产生 API 费用
.\.venv\Scripts\python.exe -m testgen_agent.b3_smoke
```

每次结果保存到 `outputs/b3/<run_id>/validation.json`。该命令会向外部服务发送 `examples/relationships.py`、`examples/relationships.md` 和 Prompt 内容；仅在明确允许发送这些数据后运行。它会检查关系 Schema、源码证据、入口、策略及单元/协作场景。B3 真实调用尚未执行，不能仅凭离线测试宣称真实验收完成。

当前共 159 项自身测试通过，其中 B1 原始契约新增 60 项、B1 关系扩展新增 27 项、B2 新增 18 项、B3 新增 21 项；自动测试不发送真实 API 请求。

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

后续任务将在 `outputs/<run_id>/` 保存测试、双格式报告、轨迹及每轮快照；具体状态和验收约定见 Design。当前配置检查不会生成这些文件。

测试执行只面向本地可信课程样例；后续真实 DeepSeek 请求可能产生费用。仓库不包含真实 Key，使用者自行配置。
