import pytest

from subject import classify_packet


def test_normal_ping_empty():
    assert classify_packet("PING:") == "heartbeat"


def test_normal_data_nonempty():
    assert classify_packet("DATA:abc") == "data"


def test_boundary_data_whitespace_payload():
    assert classify_packet("DATA: ") == "data"


def test_boundary_no_colon():
    with pytest.raises(ValueError):
        classify_packet("PING")


def test_exception_multiple_colons():
    with pytest.raises(ValueError):
        classify_packet("DATA:a:b")


def test_exception_ping_with_payload():
    with pytest.raises(ValueError):
        classify_packet("PING:hello")


def test_exception_data_empty_payload():
    with pytest.raises(ValueError):
        classify_packet("DATA:")


def test_exception_unknown_kind():
    with pytest.raises(ValueError):
        classify_packet("ACK:x")


def test_exception_empty_kind():
    with pytest.raises(ValueError):
        classify_packet(":payload")


def test_exception_lowercase_kind():
    with pytest.raises(ValueError):
        classify_packet("ping:")


def test_exception_no_strip():
    with pytest.raises(ValueError):
        classify_packet("PING :")
