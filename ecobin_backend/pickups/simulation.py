import json
import logging
import threading
import time

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

SIMULATION_INTERVAL = 1.0  # seconds between position updates


def _tracking_key(tracking_id):
    return f"tracking_position:{tracking_id}"


def _simulation_key(tracking_id):
    return f"tracking_simulation:{tracking_id}"


def start_simulation(tracking_id):
    """Start a background thread that moves the operator along the route."""
    cache.set(_simulation_key(tracking_id), True, timeout=3600)

    thread = threading.Thread(
        target=_run_simulation,
        args=(tracking_id,),
        daemon=True,
    )
    thread.start()


def stop_simulation(tracking_id):
    """Stop the simulation for a given tracking."""
    cache.delete(_simulation_key(tracking_id))


def _run_simulation(tracking_id):
    """Simulate operator movement along the calculated route."""
    from pickups.models import PickupTracking
    from pickups.routing import interpolate_position

    try:
        tracking = PickupTracking.objects.get(id=tracking_id)
    except PickupTracking.DoesNotExist:
        return

    waypoints = tracking.route_data.get('waypoints', [])
    if not waypoints:
        logger.error("No waypoints for tracking %s", tracking_id)
        return

    total_duration = tracking.total_duration_seconds
    if total_duration <= 0:
        total_duration = 300  # default 5 minutes

    speed_multiplier = getattr(settings, 'TRACKING_SPEED_MULTIPLIER', 60)
    interval = SIMULATION_INTERVAL
    progress_step = (interval * speed_multiplier) / total_duration

    while cache.get(_simulation_key(tracking_id)):
        tracking.refresh_from_db()

        if tracking.status != 'EN_ROUTE':
            break

        new_progress = min(tracking.progress + progress_step, 1.0)
        pos = interpolate_position(waypoints, new_progress)

        if pos:
            tracking.current_latitude = pos['lat']
            tracking.current_longitude = pos['lng']
            tracking.progress = new_progress

            cache.set(
                _tracking_key(tracking_id),
                json.dumps({
                    "lat": str(pos['lat']),
                    "lng": str(pos['lng']),
                    "progress": round(new_progress, 4),
                    "status": tracking.status,
                }),
                timeout=300,
            )

            if new_progress >= 1.0:
                from django.utils import timezone
                tracking.status = 'ARRIVED'
                tracking.arrived_at = timezone.now()
                tracking.save(update_fields=[
                    'current_latitude', 'current_longitude', 'progress',
                    'status', 'arrived_at', 'updated_at',
                ])
                stop_simulation(tracking_id)
                break

            tracking.save(update_fields=[
                'current_latitude', 'current_longitude', 'progress', 'updated_at',
            ])

        time.sleep(interval)


def get_operator_position(tracking_id):
    """Get the current cached position of the operator."""
    raw = cache.get(_tracking_key(tracking_id))
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
