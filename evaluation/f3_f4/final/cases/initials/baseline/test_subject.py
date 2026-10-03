from subject import initials


def test_initials_normal_basic():
    assert initials("hello world") == "HW"


def test_initials_normal_multi_whitespace():
    assert initials("  foo\tbar\n baz ") == "FBB"


def test_initials_normal_single_word():
    assert initials("python") == "P"


def test_initials_boundary_empty():
    assert initials("") == ""


def test_initials_boundary_all_whitespace():
    assert initials("   \t\n  ") == ""


def test_initials_branch_multichar_upper():
    assert initials("straße test") == "STEST"


def test_initials_branch_punctuation_cjk():
    assert initials("hi, 你好") == "H你"
