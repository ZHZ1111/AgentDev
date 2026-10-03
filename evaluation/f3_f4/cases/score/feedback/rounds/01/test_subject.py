import pytest

from subject import score_band


def test_normal_low_in_range():
    assert score_band(10) == "low"


def test_normal_middle_in_range():
    assert score_band(70) == "middle"


def test_normal_high_in_range():
    assert score_band(90) == "high"


@pytest.mark.parametrize("value, expected", [(0, "low"), (59, "low")])
def test_boundary_low_edges(value, expected):
    assert score_band(value) == expected


@pytest.mark.parametrize("value, expected", [(60, "middle"), (79, "middle")])
def test_boundary_middle_edges(value, expected):
    assert score_band(value) == expected


@pytest.mark.parametrize("value, expected", [(80, "high"), (100, "high")])
def test_boundary_high_edges(value, expected):
    assert score_band(value) == expected


@pytest.mark.parametrize("value", [-1, 101])
def test_exception_out_of_range(value):
    with pytest.raises(ValueError):
        score_band(value)


def test_branch_high_checked_before_middle():
    assert score_band(85) == "high"
