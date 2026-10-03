import pytest

from subject import calculate_total


@pytest.mark.parametrize(
    "unit_price, quantity, expected",
    [
        (12, 3, 36),
        (0, 5, 0),
        (12, 0, 0),
        (0, 0, 0),
        (1, 1, 1),
        (1000000, 1000000, 1000000000000),
    ],
)
def test_calculate_total_verifiable_cases(unit_price, quantity, expected):
    assert calculate_total(unit_price, quantity) == expected


def test_calculate_total_returns_product_of_operands():
    assert calculate_total(7, 6) == 42


def test_calculate_total_does_not_constrain_result_upper_bound():
    assert calculate_total(10**12, 10**12) == 10**24
