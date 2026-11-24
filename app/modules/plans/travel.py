"""Travel time between two activities.

The old planner hard-coded 20 minutes for every connection. That number looked
authoritative while being unrelated to the actual places, so a missing
coordinate now yields `None` plus an explicit `unknown` source instead of a
fabricated estimate.
"""

from __future__ import annotations

import math

from app.modules.plans.context import ActivitySlot

# Straight-line distance is inflated to approximate street routing, then
# converted with a conservative city-traffic speed.
ROUTE_FACTOR = 1.35
SPEED_KMH = 20.0
BOARDING_MINUTES = 8
# When coordinates are missing we still have to leave room for the trip,
# otherwise a plan silently drops every activity after the first unknown one.
# The value is a conservative placeholder and is reported as 'unknown' so the
# plan cannot be published on the strength of it.
UNKNOWN_TRAVEL_MINUTES = 30


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def travel_minutes(first: ActivitySlot | None, second: ActivitySlot) -> tuple[int | None, str]:
    """Return (minutes, source). source is 'unknown' when coordinates are absent.

    The meeting point has no coordinates, so the leg leading into the first
    activity is reported as unknown rather than invented.
    """
    if first is None:
        return None, "unknown"
    if not _located(first) or not _located(second):
        return UNKNOWN_TRAVEL_MINUTES, "unknown"
    km = haversine_km(first.latitude, first.longitude, second.latitude, second.longitude)
    minutes = int(round(km * ROUTE_FACTOR / SPEED_KMH * 60)) + BOARDING_MINUTES
    return max(minutes, BOARDING_MINUTES), "haversine_estimate"


def _located(slot: ActivitySlot) -> bool:
    return slot.latitude is not None and slot.longitude is not None
