from subject import classify


def test_positive():
    assert classify(1) == "nonnegative"


def test_negative():
    assert classify(-1) == "negative"
