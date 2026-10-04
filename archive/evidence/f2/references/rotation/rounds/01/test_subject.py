# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import rotate_left

def test_rotate_empty():
    args = [[], 0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == []
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_empty_many():
    args = [[], 7]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == []
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_single():
    args = [[4], 5]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [4]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_zero():
    args = [[1, 2, 3], 0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [1, 2, 3]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_one():
    args = [[1, 2, 3], 1]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [2, 3, 1]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_multiple():
    args = [[1, 2, 3], 3]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [1, 2, 3]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_large():
    args = [[1, 2, 3], 4]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [2, 3, 1]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_rotate_duplicates():
    args = [[1, 1, 2], 2]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = rotate_left(*args, **kwargs)
    assert actual == [2, 1, 1]
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before
