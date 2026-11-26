import os
import ipaddress
from pathlib import Path
import tomllib
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, model_validator, field_validator

from .models import Identifier, Model
from habitat.common.http import bearer_token, validate_service_url
from habitat.compute.environment import EnvironmentConfig
from habitat.vision.cameras import CameraConfig
from habitat.vision.camera_discovery import CameraDiscoveryConfig
from habitat.saas.video import VideoUploadConfig


class SensorConfig(Model):
    id: Identifier
    unit: Literal["degC", "percent_rh", "lux"]
    min_value: float
    max_value: float

    @model_validator(mode="after")
    def bounds(self):
        if self.min_value >= self.max_value:
            raise ValueError("sensor min_value must be below max_value")
        return self


class Guard(Model):
    sensor_id: Identifier
    minimum: float | None = None
    maximum: float | None = None

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("guard needs a minimum or maximum")
        if self.minimum is not None and self.maximum is not None and self.minimum >= self.maximum:
            raise ValueError("guard minimum must be below maximum")
        return self


class ActuatorConfig(Model):
    id: Identifier
    max_on_s: float = Field(gt=0, le=3600)
    cooldown_s: float = Field(default=0, ge=0, le=86400)
    required_sensors: list[Identifier] = Field(min_length=1)
    guards: list[Guard] = Field(default_factory=list)


class Policy(Model):
    actuator_id: Identifier
    sensor_id: Identifier
    direction: Literal["below", "above"]
    on_threshold: float
    off_threshold: float
    duration_s: float = Field(gt=0)

    @model_validator(mode="after")
    def hysteresis(self):
        if self.direction == "below" and self.on_threshold >= self.off_threshold:
            raise ValueError("below policy requires on_threshold < off_threshold")
        if self.direction == "above" and self.on_threshold <= self.off_threshold:
            raise ValueError("above policy requires on_threshold > off_threshold")
        return self


class CageConfig(Model):
    id: Identifier
    node_id: Identifier
    geometry_revision: int = Field(default=1, ge=1)
    placement_revision: int = Field(default=1, ge=1)
    stale_after_s: float = Field(default=15, gt=0, le=300)
    sensors: list[SensorConfig] = Field(min_length=1, max_length=64)
    actuators: list[ActuatorConfig] = Field(min_length=1, max_length=32)
    policies: list[Policy] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        sensors = {s.id: s for s in self.sensors}
        actuators = {a.id: a for a in self.actuators}
        if len(sensors) != len(self.sensors) or len(actuators) != len(self.actuators):
            raise ValueError("duplicate sensor/actuator IDs")
        for actuator in self.actuators:
            if not set(actuator.required_sensors) <= sensors.keys():
                raise ValueError("unknown required sensor")
            for guard in actuator.guards:
                if guard.sensor_id not in actuator.required_sensors:
                    raise ValueError("guard sensors must also be required sensors")
        targets = set()
        for policy in self.policies:
            if policy.actuator_id not in actuators or policy.sensor_id not in sensors:
                raise ValueError("unknown policy actuator/sensor")
            if policy.sensor_id not in actuators[policy.actuator_id].required_sensors:
                raise ValueError("policy sensor must be a required sensor")
            if policy.duration_s > actuators[policy.actuator_id].max_on_s:
                raise ValueError("policy duration exceeds actuator limit")
            if policy.actuator_id in targets:
                raise ValueError("only one policy per actuator")
            targets.add(policy.actuator_id)
        return self


class MQTTConfig(Model):
    host: str = "127.0.0.1"
    port: int = Field(default=1883, ge=1, le=65535)
    username: str = "habitat-gateway"
    password_env: str = "HABITAT_MQTT_PASSWORD"
    tls_ca: str | None = None


class R15Zone(Model):
    zone: int = Field(strict=True, ge=1, le=3)
    cage_id: Identifier
    actuator_id: Identifier


class R15BridgeConfig(Model):
    enabled: bool = False
    outputs_locked: bool = True
    central_cage_id: Identifier | None = None
    zones: list[R15Zone] = Field(default_factory=list, max_length=3)


class ServerConfig(Model):
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def valid_host(cls, value):
        if value != "localhost":
            ipaddress.ip_address(value)
        return value


class CloudConfig(Model):
    enabled: bool = False
    endpoint: AnyHttpUrl | None = None
    token_env: str = "HABITAT_CLOUD_TOKEN"
    interval_s: float = Field(default=5, ge=1, le=300)
    timeout_s: float = Field(default=10, ge=1, le=30)
    batch_size: int = Field(default=100, ge=1, le=1000)
    retry_max_s: float = Field(default=60, ge=1, le=3600)

    @model_validator(mode="after")
    def destination(self):
        if self.enabled and self.endpoint is None:
            raise ValueError("cloud.enabled requires cloud.endpoint")
        if self.retry_max_s < self.interval_s:
            raise ValueError("cloud.retry_max_s must be at least interval_s")
        if self.endpoint:
            validate_service_url(self.endpoint, "cloud.endpoint")
        return self


class LiveSceneBinding(Model):
    model_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    cage_id: Identifier
    object_id: int = Field(strict=True, ge=1, le=65535)
    actuator_id: Identifier
    checkpoint_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    geometry_revision: int = Field(strict=True, ge=1)
    placement_revision: int = Field(strict=True, ge=1)


class CameraIRConfig(Model):
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:8093"
    token_env: str = Field(default="HABITAT_IR_BRIDGE_TOKEN", pattern=r"^[A-Z][A-Z0-9_]*$")
    cage_ids: list[Identifier] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def local_bridge(self):
        address = urlsplit(self.endpoint)
        try:
            local = ipaddress.ip_address(address.hostname or "").is_loopback
            port = address.port
        except ValueError:
            local, port = False, None
        if (address.scheme != "http" or not local or not port or
                address.username is not None or address.password is not None or
                address.path not in ("", "/") or address.query or address.fragment):
            raise ValueError("camera_ir.endpoint must be an explicit loopback HTTP host and port")
        if len(set(self.cage_ids)) != len(self.cage_ids) or (self.enabled and not self.cage_ids):
            raise ValueError("camera_ir requires distinct explicit cage_ids when enabled")
        return self


class Settings(Model):
    site_id: Identifier = "STORE-001"
    gateway_id: Identifier = "PI-001"
    transport: Literal["simulated", "mqtt"] = "simulated"
    database: str = "data/habitat.sqlite3"
    command_ttl_s: int = Field(default=10, ge=1, le=60)
    clock_tolerance_s: float = Field(default=2, ge=0, le=5)
    hardware_outputs_enabled: bool = True
    mqtt: MQTTConfig = Field(default_factory=MQTTConfig)
    r15_bridge: R15BridgeConfig = Field(default_factory=R15BridgeConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    cloud: CloudConfig = Field(default_factory=CloudConfig)
    video_upload: VideoUploadConfig = Field(default_factory=VideoUploadConfig)
    camera_ir: CameraIRConfig = Field(default_factory=CameraIRConfig)
    camera_discovery: CameraDiscoveryConfig = Field(default_factory=CameraDiscoveryConfig)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    cameras: list[CameraConfig] = Field(default_factory=list, max_length=16)
    livescene_bindings: list[LiveSceneBinding] = Field(default_factory=list, max_length=512)
    cages: list[CageConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_cages(self):
        if len({c.id for c in self.cages}) != len(self.cages):
            raise ValueError("duplicate cage IDs")
        if len({c.node_id for c in self.cages}) != len(self.cages):
            raise ValueError("each cage needs a distinct node_id")
        cages = {c.id: c for c in self.cages}
        if any(cage not in cages for cage in self.camera_ir.cage_ids):
            raise ValueError("camera_ir references unknown cage")
        bridge = self.r15_bridge
        if bridge.enabled and (self.transport != "mqtt" or bridge.central_cage_id not in cages or not bridge.zones):
            raise ValueError("R15 requires MQTT, a configured central_cage_id and explicit zones")
        if len({z.zone for z in bridge.zones}) != len(bridge.zones) or len({(z.cage_id, z.actuator_id) for z in bridge.zones}) != len(bridge.zones):
            raise ValueError("R15 zones and cage/actuator mappings must be unique")
        for zone in bridge.zones:
            if zone.cage_id not in cages or zone.actuator_id not in {a.id for a in cages[zone.cage_id].actuators}:
                raise ValueError("R15 zone references unknown cage/actuator")
        for target in self.environment.targets:
            if target.cage_id not in cages:
                raise ValueError("environment target references unknown cage")
            sensors = {s.id: s.unit for s in cages[target.cage_id].sensors}
            if [sensors.get(s) for s in target.sensor_ids] != ["degC", "percent_rh", "degC", "degC"]:
                raise ValueError("environment input order must be air temperature, RH, hot probe, cool probe")
        if len({c.id for c in self.cameras}) != len(self.cameras):
            raise ValueError("duplicate camera IDs")
        if self.camera_discovery.enabled and any(c.is_network and c.view is None for c in self.cameras):
            raise ValueError("camera_discovery requires explicit top/front views for network cameras")
        if not self.camera_discovery.enabled and any(c.source_type == "rtsp_h264" for c in self.cameras):
            raise ValueError("RTSP H264 requires camera_discovery identity verification")
        if self.video_upload.enabled and any(c.source_type == "rtsp_h264" for c in self.cameras):
            raise ValueError("RTSP H264 currently supports verified camera viewer delivery, not video_upload")
        if self.video_upload.enabled and not any(c.live_stream for c in self.cameras):
            raise ValueError("video_upload requires at least one camera with live_stream enabled")
        paths = [c.device for c in self.cameras if c.device]
        if len(paths) != len(set(paths)) or any(c.cage_id not in cages for c in self.cameras):
            raise ValueError("camera mapping must have unique devices and known cages")
        urls = [c.url for c in self.cameras if c.url]
        if len(urls) != len(set(urls)):
            raise ValueError("camera mapping must have unique network sources")
        views = [(c.cage_id, c.view) for c in self.cameras if c.view is not None]
        if len(views) != len(set(views)):
            raise ValueError("camera views must be unique within each cage")
        bound = set()
        for binding in self.livescene_bindings:
            key = (binding.model_id, binding.cage_id, binding.object_id)
            cage = cages.get(binding.cage_id)
            if key in bound:
                raise ValueError("duplicate LiveScene object binding")
            if cage is None or binding.actuator_id not in {a.id for a in cage.actuators}:
                raise ValueError("LiveScene binding references unknown cage/actuator")
            if (binding.geometry_revision, binding.placement_revision) != (cage.geometry_revision, cage.placement_revision):
                raise ValueError("LiveScene binding revisions must match cage configuration")
            bound.add(key)
        return self


def load_settings(path: str | Path) -> Settings:
    with open(path, "rb") as stream:
        return Settings.model_validate(tomllib.load(stream))


def api_token(settings: Settings) -> str | None:
    token = os.environ.get("HABITAT_API_TOKEN")
    if settings.transport == "mqtt" and (not token or len(token) < 32):
        raise ValueError("MQTT mode requires HABITAT_API_TOKEN with at least 32 characters")
    return token


def cloud_token(settings: Settings) -> str | None:
    if not settings.cloud.enabled:
        return None
    return bearer_token(settings.cloud.token_env, usage="cloud sync")


def video_token(settings: Settings) -> str | None:
    if not settings.video_upload.enabled:
        return None
    return bearer_token(settings.video_upload.token_env, usage="video upload")
