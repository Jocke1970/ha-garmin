import pytest

from ha_garmin.fitness.strain import (
    calibrate_personal_trimp_max,
    compute_strain_score,
    count_consecutive_hard_days,
)


def test_strain_score_is_bounded_and_monotonic():
    assert compute_strain_score(0) == 0.0
    assert compute_strain_score(-10) == 0.0
    assert compute_strain_score(50) < compute_strain_score(150)
    assert compute_strain_score(10_000) <= 21.0


def test_strain_score_matches_documented_curve():
    assert compute_strain_score(250, personal_trimp_max=250) == 13.27


def test_strain_score_validates_personal_max():
    with pytest.raises(ValueError, match="positive"):
        compute_strain_score(100, personal_trimp_max=0)


def test_personal_trimp_calibration_waits_for_enough_sessions():
    assert calibrate_personal_trimp_max([10.0] * 29) is None
    values = [float(value) for value in range(1, 31)]
    assert calibrate_personal_trimp_max(values) == 36.0


def test_personal_trimp_calibration_ignores_non_positive_sessions():
    values = [0.0, -2.0] + [10.0] * 30
    assert calibrate_personal_trimp_max(values) == 12.0


def test_personal_trimp_calibration_validates_options():
    with pytest.raises(ValueError, match="min_sessions"):
        calibrate_personal_trimp_max([10.0], min_sessions=0)
    with pytest.raises(ValueError, match="multiplier"):
        calibrate_personal_trimp_max([10.0], multiplier=1.0)


def test_consecutive_hard_days_counts_from_today_backwards():
    assert count_consecutive_hard_days([16, 15, 14, 18]) == 2
    assert count_consecutive_hard_days([16, 15, 14.1, 8]) == 3
    assert count_consecutive_hard_days([10, 18, 18]) == 0


def test_consecutive_hard_days_validates_threshold():
    with pytest.raises(ValueError, match="negative"):
        count_consecutive_hard_days([10], threshold=-1)
