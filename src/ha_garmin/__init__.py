"""Python client for Garmin Connect API."""

from .activity_types import GarminClient
from .auth import GarminAuth
from .exceptions import (
    GarminAuthError,
    GarminConnectError,
    GarminMFARequired,
    GarminRateLimitError,
)
from .history import GarminHistoryClient, TrimpTrainingContext

__all__ = [
    "GarminAuth",
    "GarminAuthError",
    "GarminClient",
    "GarminConnectError",
    "GarminHistoryClient",
    "GarminMFARequired",
    "GarminRateLimitError",
    "TrimpTrainingContext",
]

__version__ = "0.1.38"
