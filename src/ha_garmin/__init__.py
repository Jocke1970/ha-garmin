"""Python client for Garmin Connect API."""

from .activity_types import GarminClient
from .auth import GarminAuth
from .exceptions import (
    GarminAuthError,
    GarminConnectError,
    GarminMFARequired,
    GarminRateLimitError,
)

__all__ = [
    "GarminAuth",
    "GarminAuthError",
    "GarminClient",
    "GarminConnectError",
    "GarminMFARequired",
    "GarminRateLimitError",
]

__version__ = "0.1.38"
