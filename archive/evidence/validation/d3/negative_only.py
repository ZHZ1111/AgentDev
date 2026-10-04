from subject import classify


def test_negative_only():
    assert classify(-1) == "negative"
