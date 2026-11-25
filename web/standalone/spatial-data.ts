import type { Point, SpatialLayout } from './live-data';

export type Position = [number, number, number];
export type SpatialReading = SpatialLayout['sensors'][number] & { value: number };

export function spatialReadings(layout: SpatialLayout, readings: Point['readings']): SpatialReading[] {
  return layout.sensors.flatMap(sensor => {
    const reading = readings[sensor.id];
    return reading?.quality === 'valid' && reading.value !== null && Number.isFinite(reading.value)
      ? [{ ...sensor, value: reading.value }] : [];
  });
}

export function interpolateTemperature(position: Position, sensors: SpatialReading[]): number | null {
  let weighted = 0, weights = 0;
  for (const sensor of sensors) {
    const distanceSquared = position.reduce((sum, coordinate, i) => sum + (coordinate - sensor.positionCm[i]) ** 2, 0);
    if (distanceSquared < 1e-10) return sensor.value;
    const weight = 1 / distanceSquared;
    weighted += sensor.value * weight;
    weights += weight;
  }
  return weights ? weighted / weights : null;
}

export function spatialHistory(points: Point[], layout: SpatialLayout) {
  return points.filter(point => point.data_source === 'sensor' && Number.isFinite(Date.parse(point.at))
    && point.geometry_revision === layout.geometryRevision && point.placement_revision === layout.placementRevision);
}

export function projectPoint(position: Position, dimensions: Position, yaw: number, pitch: number) {
  const [x, y, z] = position.map((coordinate, i) => coordinate - dimensions[i] / 2);
  const depth = x * Math.sin(yaw) + y * Math.cos(yaw);
  return { x: x * Math.cos(yaw) - y * Math.sin(yaw),
    y: -z * Math.cos(pitch) + depth * Math.sin(pitch),
    depth: depth * Math.cos(pitch) + z * Math.sin(pitch) };
}
