"""列表均值参考实现。"""

def safe_mean(values):
    """空列表返回 0.0，否则为 sum / len；不修改输入。"""
    if not values:
        return 0.0
    return sum(values) / len(values)

