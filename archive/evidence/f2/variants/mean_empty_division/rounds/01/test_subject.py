# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import safe_mean

def test_mean_empty():
    args = [[]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = safe_mean(*args, **kwargs)
    assert actual == 0
    assert type(actual) is float
    assert (args, kwargs) == before

def test_mean_zero():
    args = [[0]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = safe_mean(*args, **kwargs)
    assert actual == 0
    assert type(actual) is float
    assert (args, kwargs) == before

def test_mean_fraction():
    args = [[1, 2]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = safe_mean(*args, **kwargs)
    assert actual == 1.5
    assert type(actual) is float
    assert (args, kwargs) == before

def test_mean_signed():
    args = [[-2, 2]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = safe_mean(*args, **kwargs)
    assert actual == 0
    assert type(actual) is float
    assert (args, kwargs) == before

def test_mean_duplicates():
    args = [[2, 2, 5]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = safe_mean(*args, **kwargs)
    assert actual == 3
    assert type(actual) is float
    assert (args, kwargs) == before
