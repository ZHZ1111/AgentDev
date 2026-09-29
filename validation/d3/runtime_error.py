from subject import classify


def test_runtime_error():
    classify(1)
    raise ValueError("controlled_runtime_error")
