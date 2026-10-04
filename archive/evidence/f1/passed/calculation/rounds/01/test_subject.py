from subject import calculate_total


def test_unit_12x3():
    assert calculate_total(12, 3) == 36


def test_unit_zero_price():
    assert calculate_total(0, 5) == 0


def test_unit_zero_quantity():
    assert calculate_total(12, 0) == 0


def test_unit_zero_both():
    assert calculate_total(0, 0) == 0


def test_unit_identity():
    assert calculate_total(1, 1) == 1


def test_unit_large():
    assert calculate_total(1000000, 1000000) == 1000000000000
