# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import score_band

def test_score_negative():
    args = [-1]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        score_band(*args, **kwargs)
    assert (args, kwargs) == before

def test_score_zero():
    args = [0]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'low'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_59():
    args = [59]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'low'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_60():
    args = [60]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'middle'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_79():
    args = [79]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'middle'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_80():
    args = [80]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'high'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_100():
    args = [100]
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = score_band(*args, **kwargs)
    assert actual == 'high'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_score_above():
    args = [101]
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        score_band(*args, **kwargs)
    assert (args, kwargs) == before
