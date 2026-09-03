"""Python client for Garmin Connect API."""

from .auth import GarminAuth
from .client import GarminClient
from .exceptions import (
    GarminAuthError,
    GarminConnectError,
    GarminMFARequired,
    GarminRateLimitError,
)
from .history import GarminHistoryClient

__all__ = [
    "GarminAuth",
    "GarminAuthError",
    "GarminClient",
    "GarminConnectError",
    "GarminHistoryClient",
    "GarminMFARequired",
    "GarminRateLimitError",
]

__version__ = "0.1.0"
