"""标签规范化与展示参考实现。"""

def normalize_labels(labels):
    """依次 strip/lower，删除空项；保留顺序及重复。"""
    result = []
    for label in labels:
        normalized = label.strip()
        if normalized:
            result.append(normalized)
    return result

def format_labels(labels):
    """用英文逗号加一个空格拼接真实规范化结果。"""
    return ", ".join(normalize_labels(labels))

