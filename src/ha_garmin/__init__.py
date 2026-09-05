"""Python client for Garmin Connect API."""

from .auth import GarminAuth
from .client import GarminClient
from .exceptions import (
    GarminAuthError,
    GarminConnectError,
    GarminMFARequired,
    GarminRateLimitError,
)
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
    "InsightSnapshot",
    "TrimpTrainingContext",
    "build_insight_snapshot",
]

__version__ = "0.1.0"
