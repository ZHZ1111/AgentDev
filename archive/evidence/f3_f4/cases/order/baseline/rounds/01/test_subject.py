import pytest

from subject import validate_quantity, subtotal, order_total


def test_validate_quantity_normal():
    assert validate_quantity(5) == 5


def test_validate_quantity_nonint_typeerror():
    with pytest.raises(TypeError):
        validate_quantity(2.5)


def test_validate_quantity_bool_typeerror():
    with pytest.raises(TypeError):
        validate_quantity(True)


def test_validate_quantity_nonpositive_valueerror():
    with pytest.raises(ValueError):
        validate_quantity(0)


def test_validate_quantity_negative_valueerror():
    with pytest.raises(ValueError):
        validate_quantity(-1)


def test_subtotal_positive():
    assert subtotal(7, 3) == 21


def test_subtotal_zero_quantity():
    assert subtotal(7, 0) == 0


def test_subtotal_zero_unit_price():
    assert subtotal(0, 9) == 0


def test_order_total_normal():
    assert order_total(4, 6) == 24


def test_order_total_typeerror_propagation():
    with pytest.raises(TypeError):
        order_total(4, 2.5)


def test_order_total_valueerror_propagation():
    with pytest.raises(ValueError):
        order_total(4, 0)
