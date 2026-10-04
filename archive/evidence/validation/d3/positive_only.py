from subject import classify


def test_positive_only():
    assert classify(1) == "nonnegative"
