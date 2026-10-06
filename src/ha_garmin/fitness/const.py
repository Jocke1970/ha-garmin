"""Constants and version identifiers for Garmin Fitness calculations."""

GARMIN_FITNESS_ALGORITHM_VERSION = 2

LOAD_SOURCE_GARMIN = "garmin"
LOAD_SOURCE_TRIMP = "trimp"
# Algorithm v2 keeps canonical TRIMP as the selected load source and corrects
# Banister's sex-specific multiplicative coefficient. Keep this explicit so
# persistence adapters never mix Garmin Load and TRIMP.
CANONICAL_LOAD_SOURCE = LOAD_SOURCE_TRIMP

CTL_PERIOD_DAYS = 42
ATL_PERIOD_DAYS = 7
ACWR_ACUTE_DAYS = 7
ACWR_CHRONIC_DAYS = 28
RAMP_RATE_PERIOD_DAYS = 7

BANISTER_TRIMP_A_MALE = 0.64
BANISTER_TRIMP_A_FEMALE = 0.86
BANISTER_TRIMP_K_MALE = 1.92
BANISTER_TRIMP_K_FEMALE = 1.67
DEFAULT_PERSONAL_TRIMP_MAX = 250.0
STRAIN_HARD_DAY_THRESHOLD = 14.0
LOAD_FOCUS_DOMINANCE_RATIO = 1.5
# Transparent v1 heuristic used for the Home Assistant low/high aerobic split.
# Garmin Aerobic Training Effect >= 3.0 contributes to high aerobic; positive
# values below 3.0 contribute to low aerobic. Anaerobic TE is tracked separately.
LOAD_FOCUS_HIGH_AEROBIC_THRESHOLD = 3.0
