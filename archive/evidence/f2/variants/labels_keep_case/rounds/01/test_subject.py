# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import format_labels, normalize_labels

def test_labels_empty():
    args = [[]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = normalize_labels(*args, **kwargs)
    assert actual == []
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_labels_mixed():
    args = [[' A ', '', 'b']]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = normalize_labels(*args, **kwargs)
    assert actual == ['a', 'b']
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_labels_unicode():
    args = [[' 中文 ', 'A', 'a']]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = normalize_labels(*args, **kwargs)
    assert actual == ['中文', 'a', 'a']
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_labels_whitespace():
    args = [[' ', '\t']]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = normalize_labels(*args, **kwargs)
    assert actual == []
    assert type(actual) is list
    assert all(actual is not value for value in args if isinstance(value, list))
    assert (args, kwargs) == before

def test_formatted_order():
    args = [[' B ', '', 'A', 'a']]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = format_labels(*args, **kwargs)
    assert actual == 'b, a, a'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_formatted_empty():
    args = [[]]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = format_labels(*args, **kwargs)
    assert actual == ''
    assert type(actual) is str
    assert (args, kwargs) == before

def test_formatted_unicode():
    args = [[' 中文 ', 'X']]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = format_labels(*args, **kwargs)
    assert actual == '中文, x'
    assert type(actual) is str
    assert (args, kwargs) == before
