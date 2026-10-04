"""留出集：列表左旋参考实现。"""

def rotate_left(values, steps):
    """新列表向左旋 steps 个位置，空列表直接返回空列表。"""
    if not values:
        return []
    offset = steps % len(values)
    return values[offset:] + values[:offset]

