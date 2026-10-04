# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import clamp_int, compact_runs

def test_clamp_below():
    args = [-3, -2, 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == -2
    assert type(actual) is int
    assert (args, kwargs) == before

def test_clamp_lower():
    args = [-2, -2, 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == -2
    assert type(actual) is int
    assert (args, kwargs) == before

def test_clamp_inside():
    args = [1, -2, 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == 1
    assert type(actual) is int
    assert (args, kwargs) == before

def test_clamp_upper():
    args = [4, -2, 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == 4
    assert type(actual) is int
    assert (args, kwargs) == before

def test_clamp_above():
    args = [5, -2, 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == 4
    assert type(actual) is int
    assert (args, kwargs) == before

def test_clamp_single():
    args = [7, 2, 2]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = clamp_int(*args, **kwargs)
    assert actual == 2
    assert type(actual) is int
    assert (args, kwargs) == before

def test_compact_empty():
    args = [[]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = compact_runs(*args, **kwargs)
    assert actual == []
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_compact_single():
    args = [[4]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = compact_runs(*args, **kwargs)
    assert actual == [4]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_compact_adjacent():
    args = [[1, 1, 2, 2, 1]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = compact_runs(*args, **kwargs)
    assert actual == [1, 2, 1]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_compact_nonadjacent():
    args = [[1, 2, 1]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = compact_runs(*args, **kwargs)
    assert actual == [1, 2, 1]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_compact_negative():
    args = [[-1, -1, 0, 0]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = compact_runs(*args, **kwargs)
    assert actual == [-1, 0]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before
