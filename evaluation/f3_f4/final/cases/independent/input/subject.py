"""同文件独立函数对照，不构造两者的组合流程。"""

def clamp_int(value, lower, upper):
    """把整数限制到闭区间 [lower, upper]。"""
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value

def compact_runs(values):
    """仅压缩连续相等项，不做全局去重。"""
    result = []
    for value in values:
        if not result or result[-1] != value:
            result.append(value)
    return result

