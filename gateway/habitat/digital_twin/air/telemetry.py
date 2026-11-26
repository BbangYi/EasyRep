"""Shared sensor contract checks for live receipt and historical display inputs."""
import math

from habitat_gateway.models import Telemetry


def validate_telemetry(raw, cage, now, max_future_skew=5.):
    """Return a canonical sample; old measurements remain valid display inputs.

    Freshness is a property of the resulting view, not a reason to erase a real
    measurement. This validator never changes the source ID or measurement time.
    """
    if (not isinstance(raw, dict) or raw.get('data_source') != 'sensor'
            or type(raw.get('schema_version')) is not int or raw['schema_version'] != 1):
        raise ValueError('sensor_contract_required')
    sample = Telemetry.model_validate(raw)
    if (sample.geometry_revision, sample.placement_revision) != (
            cage.geometry_revision, cage.placement_revision):
        raise ValueError('sensor_revision_mismatch')
    if (sample.sampled_at - now).total_seconds() > max_future_skew:
        raise ValueError('future_sensor_timestamp')
    sensors = {sensor.id: sensor for sensor in cage.sensors}
    for sensor_id in ('T1', 'T2', 'T3'):
        reading, spec = sample.readings.get(sensor_id), sensors.get(sensor_id)
        raw_value = raw.get('readings', {}).get(sensor_id, {}).get('value')
        if (spec is None or spec.unit != 'degC' or reading is None or reading.quality != 'valid'
                or type(raw_value) not in (int, float) or not math.isfinite(reading.value)
                or not spec.min_value <= reading.value <= spec.max_value):
            raise ValueError('invalid_temperature_triplet')
    return sample
