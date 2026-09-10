import logging
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)

# Nominatim — free, no API key required
# user_agent must be unique per project per Nominatim usage policy
_geocoder = Nominatim(user_agent="ecobin_waste_management_v1")


def geocode_place(place_text):
    """
    Convert a place name/address to (latitude, longitude) using
    OpenStreetMap Nominatim.

    Returns:
        (lat, lng) as floats, or None if geocoding fails.
    """
    if not place_text or not place_text.strip():
        return None

    try:
        location = _geocoder.geocode(place_text.strip(), timeout=10)
        if location:
            return (location.latitude, location.longitude)
        return None
    except GeocoderTimedOut:
        logger.warning("Nominatim timed out for place: %s", place_text)
        return None
    except GeocoderServiceError as e:
        logger.warning("Nominatim service error for place '%s': %s", place_text, e)
        return None
    except Exception as e:
        logger.warning("Geocoding failed for place '%s': %s", place_text, e)
        return None
