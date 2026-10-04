# F2 v1 小型评测集

本集新增 12 个函数，组织为 8 个单文件任务。四类各 3 个函数，开发集 8 个函数（4 个任务），留出集 4 个函数（4 个任务）。每个 `.py` 有相邻公开 `.md` 规格；手写关键预期和关系标注独立保存。

| 划分 | 任务 | 函数 | 分类 |
|---|---|---|---|
| 开发 | order | validate_quantity、subtotal、order_total | 异常与多分支、数字边界、异常与多分支 |
| 开发 | labels | normalize_labels、format_labels | 字符串（2 个） |
| 开发 | independent | clamp_int、compact_runs | 数字边界、列表 |
| 开发 | mean | safe_mean | 列表 |
| 留出 | score | score_band | 数字边界 |
| 留出 | initials | initials | 字符串 |
| 留出 | rotation | rotate_left | 列表 |
| 留出 | packet | classify_packet | 异常与多分支 |

order 的合理入口是 `order_total`，确认调用 `validate_quantity` 和 `subtotal`，需验证校验结果进入计价以及异常传播。labels 的合理入口是 `format_labels`，确认调用 `normalize_labels`，需验证去空、大小写规范化、顺序和重复项的组合结果。independent 的两函数没有同文件调用边或组合规格，作为独立函数对照。字符串/列表方法等静态无法安全绑定的调用仍按未知调用保留，不被关系标注升级为确认边。

`annotations/` 中的确认边含调用行和表达式、合理入口及关键组合行为的场景引用；`oracles/` 是 69 条手写预期，含具体输入、返回值/异常、返回类型及适用的新列表约束。预期预先写入，不从参考函数运行结果生成。验证还检查输入未改变。

`mutants/` 含 6 个预设错误版本，每版仅改变一个指定函数：

| 变体 | 错误 | 手写关键见证 |
|---|---|---|
| quantity_accepts_zero | 错误接受数量 0，入口未传播 ValueError | quantity_zero、order_zero |
| order_quantity_increment | 入口向计价多传一件数量 | order_valid |
| labels_keep_case | 遗漏 lower | labels_mixed、formatted_order |
| mean_empty_division | 遗漏空列表分支，产生 ZeroDivisionError | mean_empty |
| score_excludes_80 | 80 分错误划入 middle | score_80 |
| rotation_wrong_direction | 左旋误作右旋 | rotate_one、rotate_large、rotate_duplicates |

`order_quantity_increment` 保持两个组件的单元行为正确，但破坏入口的数据衔接，专门用于后续验证协作测试价值。变体并非另计为新函数；这是小型已知错误集，不是完整自动变异测试系统。

manifest 固定案例划分、函数分类、变体及见证，并对 38 份源码/规格/预期/标注文件保存 SHA256。F2 完成后应冻结此版本；需要改变内容时建立新版本并保留原实验记录。README 是说明文件，不参与数据指纹。

留出集在 F2 中只进行本地参考实现/手写预期核验，未发送给模型、未用于调 Prompt。F3 应先用开发集确定配置与 Prompt，再冻结设置进行留出评测；查看留出参考结果不能作为选择或修改 Prompt 的依据。

向模型提供的数据仅为选定的参考源码和公开行为规格（以及正式工具提取的源码事实）。不要提供 `oracles/`、`annotations/`、manifest 中的错误描述/见证、变体代码或隐藏参考测试。用户无需填写关系/入口/测试类型。

```powershell
# 验证全部正确实现、关系标注和六个已知错误，不调用模型
.\.venv\Scripts\python.exe -m testgen_agent.f2_validation
# 可单独核验划分；仅为本地样例完整性检查
.\.venv\Scripts\python.exe -m testgen_agent.f2_validation --split holdout
```

每次在 `outputs/f2/<UUID>/` 保存独立源码/手写测试、真实 pytest/coverage 原始文件、源码分析、冻结 manifest 与 validation.json；`--output` 可更改根目录。源码只统计该运行的 subject.py，Agent 自身测试覆盖率不计入其中。退出码 0 表示全部样例检查通过，1 表示结果不符；参数选择错误为 2。

2026-10-03 F2 实测：8 个正确任务的 69 条手写检查全部通过，六个变体均触发指定行为见证；所有关系标注与 AST 位置一致、原文件指纹保持不变。mean 的错误表现为目标函数内 ZeroDivisionError，不是导入或环境失败。order 的数据衔接变体通过组件单元检查，仅协作见证失败。网络请求为 0。精选结果见 `evaluation/f2_validation.json`，原始证据在 `evaluation/f2/`。这些结果证明样例和预设错误可用，不是 Agent 生成测试的覆盖提升或 Bug 检出率；F3/F4 仍待实施。

自身检查新增 23 项；F2/源码/关系回归 69 项以 `-W error` 通过，最终 F2 专项 23 项通过。compileall、pip check、git diff --check 通过。命令与结果见 `evaluation/f2_tests.json`。
