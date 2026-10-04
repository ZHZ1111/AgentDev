from subject import missing_d3_function


def test_unreachable():
    assert missing_d3_function(1) == "nonnegative"
