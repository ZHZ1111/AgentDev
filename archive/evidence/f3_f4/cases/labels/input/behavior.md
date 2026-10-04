# 标签规范化与展示
- labels 为 list[str]，每项为内置 str；域外行为未定义。
- normalize_labels 按原顺序对每项执行 str.strip() 去首尾空白，再 str.lower()。删除处理后的空字符串，保留重复；返回新列表，不修改输入。
- format_labels 调用真实 normalize_labels，用 ", "（英文逗号和一个空格）连接规范化结果；空结果为 ""。
- 例：[" B ", "", "A", "a"] 的规范化结果为 ["b", "a", "a"]，展示为 "b, a, a"。中文字符保持其 str.lower() 结果。
- 无外部副作用，不测试域外异常。

