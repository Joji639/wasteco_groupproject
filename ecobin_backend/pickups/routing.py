import json
import logging
import math
import time
import requests

logger = logging.getLogger(__name__)

OSRM_BASE = "http://router.project-osrm.org"


def calculate_route(start_lat, start_lng, end_lat, end_lng):
    """
    Calculate the best driving route between two points using OSRM.
    Returns a list of {lat, lng} waypoints along the road, or None on failure.
    """
    coords = f"{start_lng},{start_lat};{end_lng},{end_lat}"
    url = f"{OSRM_BASE}/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=true"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            logger.warning("OSRM returned no routes: %s", data.get("code"))
            return None, 0

        route = data["routes"][0]
        distance_meters = route.get("distance", 0)
        duration_seconds = route.get("duration", 0)

        coordinates = route["geometry"]["coordinates"]
        waypoints = [{"lat": c[1], "lng": c[0]} for c in coordinates]

        return waypoints, duration_seconds
    except requests.RequestException as e:
        logger.error("OSRM request failed: %s", e)
        return None, 0
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        logger.error("OSRM response parse error: %s", e)
        return None, 0


def interpolate_position(waypoints, progress):
    """
    Given a list of waypoints and a progress value (0.0 to 1.0),
    return the interpolated {lat, lng} position along the route.
    """
    if not waypoints:
        return None

    if progress <= 0:
        return waypoints[0]
    if progress >= 1:
        return waypoints[-1]

    total_segments = len(waypoints) - 1
    segment = progress * total_segments
    index = int(segment)
    fraction = segment - index

    if index >= total_segments:
        return waypoints[-1]

    p1 = waypoints[index]
    p2 = waypoints[index + 1]

    return {
        "lat": p1["lat"] + (p2["lat"] - p1["lat"]) * fraction,
        "lng": p1["lng"] + (p2["lng"] - p1["lng"]) * fraction,
    }


def haversine_distance(lat1, lng1, lat2, lng2):
    """Calculate distance in meters between two lat/lng points."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
