# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import order_total, subtotal, validate_quantity

def test_quantity_one():
    args = [1]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = validate_quantity(*args, **kwargs)
    assert actual == 1
    assert type(actual) is int
    assert (args, kwargs) == before

def test_quantity_many():
    args = [5]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = validate_quantity(*args, **kwargs)
    assert actual == 5
    assert type(actual) is int
    assert (args, kwargs) == before

def test_quantity_zero():
    args = [0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        validate_quantity(*args, **kwargs)
    assert (args, kwargs) == before

def test_quantity_negative():
    args = [-1]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        validate_quantity(*args, **kwargs)
    assert (args, kwargs) == before

def test_quantity_bool():
    args = [True]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(TypeError):
        validate_quantity(*args, **kwargs)
    assert (args, kwargs) == before

def test_quantity_text():
    args = ['2']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(TypeError):
        validate_quantity(*args, **kwargs)
    assert (args, kwargs) == before

def test_subtotal_normal():
    args = [12, 3]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = subtotal(*args, **kwargs)
    assert actual == 36
    assert type(actual) is int
    assert (args, kwargs) == before

def test_subtotal_zero_price():
    args = [0, 5]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = subtotal(*args, **kwargs)
    assert actual == 0
    assert type(actual) is int
    assert (args, kwargs) == before

def test_subtotal_zero_quantity():
    args = [12, 0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = subtotal(*args, **kwargs)
    assert actual == 0
    assert type(actual) is int
    assert (args, kwargs) == before

def test_order_valid():
    args = [12, 3]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = order_total(*args, **kwargs)
    assert actual == 36
    assert type(actual) is int
    assert (args, kwargs) == before

def test_order_zero_price():
    args = [0, 3]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = order_total(*args, **kwargs)
    assert actual == 0
    assert type(actual) is int
    assert (args, kwargs) == before

def test_order_zero():
    args = [12, 0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        order_total(*args, **kwargs)
    assert (args, kwargs) == before

def test_order_bad_type():
    args = [10, '2']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(TypeError):
        order_total(*args, **kwargs)
    assert (args, kwargs) == before
