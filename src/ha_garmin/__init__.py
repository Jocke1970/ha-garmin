"""Python client for Garmin Connect API."""

from .activity_types import GarminClient
from .auth import GarminAuth
from .exceptions import (
    GarminAuthError,
    GarminConnectError,
    GarminMFARequired,
    GarminRateLimitError,
)
from .gear import GearItem, GearSourceRecord, build_gear_source_records
from .history import GarminHistoryClient, TrimpTrainingContext
from .insights import DailyRecoveryMetrics, InsightSnapshot, build_insight_snapshot

__all__ = [
    "DailyRecoveryMetrics",
    "GarminAuth",
    "GarminAuthError",
    "GarminClient",
    "GarminConnectError",
    "GarminHistoryClient",
    "GarminMFARequired",
    "GarminRateLimitError",
    "GearItem",
    "GearSourceRecord",
    "InsightSnapshot",
    "TrimpTrainingContext",
    "build_gear_source_records",
    "build_insight_snapshot",
]

__version__ = "0.1.38"
