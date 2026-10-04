from subject import safe_mean


def test_normal_two_elements():
    assert safe_mean([1, 2]) == 1.5


def test_normal_cancelling_mean():
    assert safe_mean([-2, 2]) == 0.0


def test_normal_non_integral_mean():
    assert safe_mean([2, 2, 5]) == 3.0


def test_boundary_empty_list():
    result = safe_mean([])
    assert result == 0.0
    assert isinstance(result, float)


def test_boundary_single_element():
    assert safe_mean([7]) == 7.0


def test_boundary_max_abs_value():
    assert safe_mean([1000000, -1000000]) == 0.0


def test_branch_empty_falsy_taken():
    assert safe_mean([]) == 0.0


def test_branch_nonempty_falsy_path_not_taken():
    assert safe_mean([4, 6]) == 5.0


def test_no_mutation_of_input():
    values = [1, 2, 3]
    original_id = id(values)
    assert safe_mean(values) == 2.0
    assert values == [1, 2, 3]
    assert id(values) == original_id
    assert len(values) == 3
