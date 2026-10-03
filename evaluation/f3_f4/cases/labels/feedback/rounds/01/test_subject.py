from subject import format_labels, normalize_labels


def test_unit_normalize_mixed():
    result = normalize_labels([" B ", "", "A", "a"])
    assert result == ["b", "a", "a"]


def test_unit_normalize_empty():
    assert normalize_labels([]) == []


def test_unit_normalize_all_empty():
    assert normalize_labels(["", "   ", "\t"]) == []


def test_unit_normalize_cjk():
    assert normalize_labels([" \u4e2d\u6587ABC "]) == ["\u4e2d\u6587abc"]


def test_unit_format_normal():
    assert format_labels([" B ", "A", "a"]) == "b, a, a"


def test_unit_format_empty():
    assert format_labels([]) == ""


def test_unit_format_all_empty_input():
    assert format_labels(["", "  "]) == ""


def test_collab_format_through_normalize():
    assert format_labels([" \u4e2d\u6587 ", "X", "x"]) == "\u4e2d\u6587, x, x"
