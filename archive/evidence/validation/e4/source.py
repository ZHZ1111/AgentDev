"""Handwritten pure branch fixture for offline E4 trace validation."""


def choose(n: int) -> int:
    """Positive -> 1, zero -> 0, negative -> -1."""
    if n > 0:
        return 1
    if n == 0:
        return 0
    return -1
