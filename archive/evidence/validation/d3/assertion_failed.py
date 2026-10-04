from subject import classify


def test_wrong_expectation():
    assert classify(1) == "negative"
