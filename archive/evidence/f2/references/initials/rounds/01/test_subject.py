# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import initials

def test_initials_empty():
    args = ['']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == ''
    assert type(actual) is str
    assert (args, kwargs) == before

def test_initials_whitespace():
    args = [' \t\n']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == ''
    assert type(actual) is str
    assert (args, kwargs) == before

def test_initials_words():
    args = ['alice Bob carol']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == 'ABC'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_initials_unicode():
    args = ['你好 世界']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == '你世'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_initials_expansion():
    args = ['ßeta alpha']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == 'SSA'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_initials_punctuation():
    args = ['_name bob']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = initials(*args, **kwargs)
    assert actual == '_B'
    assert type(actual) is str
    assert (args, kwargs) == before
