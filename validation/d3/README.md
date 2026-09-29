# D3 手写验收样例与人工期望

这些样例用于验证 D1/D2 工具，由宿主显式复制到专用工作区。它们不是模型生成产物，超时样例的 PID 标记是受控诊断。

`source.py` 只有四个可执行语句：第 1 行定义函数，第 2 行判断，第 3/4 行分别返回。判断有两个分支弧：`2 → 3`、`2 → 4`。

| 候选 | pytest 退出码 | 工具结局 | 行覆盖 | 分支覆盖 | 缺失位置 |
|---|---:|---|---:|---:|---|
| passed | 0 | passed，2 个通过项 | 4/4 | 2/2 | 无 |
| assertion_failed | 1 | assertion_failed | 3/4 | 1/2 | 行 4；弧 2→4 |
| runtime_error | 1 | execution_error | 3/4 | 1/2 | 行 4；弧 2→4 |
| import_failed | 2 | collection_error，收集 0 项 | 1/4 | 0/2 | 行 2/3/4；两个弧 |
| empty | 5 | no_tests | 0/4 | 0/2 | 四行；两个弧 |
| timeout | 被终止 | timeout，实际进入 call 1 项 | 不可用 | 不可用 | 不报告未完成数据 |
| positive_only | 0 | passed | 3/4 | 1/2 | 行 4；弧 2→4 |
| negative_only | 0 | passed | 3/4 | 1/2 | 行 3；弧 2→3 |

以上期望预先写入 `expectations.json`，不从待验证工具结果反推。单侧执行行覆盖为 75%、分支覆盖为 50%，coverage 的联合百分比不能当作行百分比。

独立参考命令不加载 Agent 结果插件，分别输出 JUnit 与 coverage JSON。JUnit 会把 call 阶段的 ValueError 记为 failure；收集错误会生成一个诊断 testcase，因此不能把该节点误算成收集到的测试项。`expectations.json` 分别保存 JUnit 原始口径与 D1 工具口径。

从项目目录重跑：

```powershell
.\.venv\Scripts\python.exe -m testgen_agent.d3_validation
```

完整产物保存到新的 `outputs/d3/<run_id>/`。只检查本地可信样例，不发送 API 请求。源码及样例原件只读；每个工具和参考运行拥有各自的源码副本和诊断目录。
