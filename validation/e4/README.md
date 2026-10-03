# E4 离线验收样例

`source.py` 是手写三分支函数；模型响应由 `testgen_agent.e4_validation` 中的手写序列提供，依次测试正数、零和负数。控制器使用真实 pytest/coverage 反馈选择补充动作，三轮达到覆盖目标。另一组使用 `examples/discount.py` 及其明确规格，验证输入 100、预期 90 的失败会停止并保留证据。

在工程根目录运行：

```powershell
.\.venv\Scripts\python.exe -m testgen_agent.e4_validation
```

每次创建新的 `outputs/e4/<UUID>/`，保存两组独立工作区和 `validation.json`；可用 `--output` 更换产物根目录。退出码 0 表示检查全部通过，1 表示结果不符合预期。验收不读取 API 配置、不发送网络请求；适配器 attempts 为模拟计数，工具执行及覆盖产物来自真实本地进程。精选提交证据在 `evaluation/e4_*`。
