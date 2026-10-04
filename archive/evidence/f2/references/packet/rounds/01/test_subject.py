# Handwritten F2 oracle materialization; not model-generated.
import pytest
from copy import deepcopy
from subject import classify_packet

def test_packet_ping():
    args = ['PING:']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = classify_packet(*args, **kwargs)
    assert actual == 'heartbeat'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_packet_data():
    args = ['DATA:x']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = classify_packet(*args, **kwargs)
    assert actual == 'data'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_packet_unicode():
    args = ['DATA:你好']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = classify_packet(*args, **kwargs)
    assert actual == 'data'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_packet_space():
    args = ['DATA: ']
    kwargs = {}
    before = deepcopy((args, kwargs))
    actual = classify_packet(*args, **kwargs)
    assert actual == 'data'
    assert type(actual) is str
    assert (args, kwargs) == before

def test_packet_no_colon():
    args = ['PING']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_many_colons():
    args = ['DATA:a:b']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_ping_payload():
    args = ['PING:x']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_empty_data():
    args = ['DATA:']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_unknown():
    args = ['OTHER:x']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_case():
    args = ['ping:']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before

def test_packet_empty_kind():
    args = [':x']
    kwargs = {}
    before = deepcopy((args, kwargs))
    with pytest.raises(ValueError):
        classify_packet(*args, **kwargs)
    assert (args, kwargs) == before
