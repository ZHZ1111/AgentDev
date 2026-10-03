"""留出集：分数边界参考实现。"""

def score_band(score):
    """0..100 分分为 low/middle/high；范围外抛 ValueError。"""
    if score < 0 or score > 100:
        raise ValueError("score")
    if score >= 80:
        return "high"
    if score >= 60:
        return "middle"
    return "low"

