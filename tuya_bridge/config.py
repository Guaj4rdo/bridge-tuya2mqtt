import re
from dataclasses import dataclass, field

import yaml


@dataclass
class DeviceConfig:
    id: str = ""
    ip: str = ""
    local_key: str = ""
    protocol: str = "3.3"
    relay_dp: str = "1"
    poll_interval: float = 3.0
    heartbeat_interval: float = 15.0


@dataclass
class MQTTConfig:
    host: str = "localhost"
    port: int = 1883
    client_id: str = "tuya-bridge"
    base_topic: str = "tuya"
    username: str = ""
    password: str = ""
    reconnect_delay: float = 5.0


@dataclass
class Config:
    device: DeviceConfig = field(default_factory=DeviceConfig)
    mqtt: MQTTConfig = field(default_factory=MQTTConfig)
    verbose: bool = False


_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ms|s|m|h)$")


def _parse_duration(val) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if not isinstance(val, str):
        raise ValueError(f"invalid duration: {val!r}")
    m = _DURATION_RE.match(val.strip())
    if not m:
        raise ValueError(f"invalid duration format: {val!r}")
    n = float(m.group(1))
    unit = m.group(2)
    if unit == "ms":
        return n / 1000.0
    if unit == "s":
        return n
    if unit == "m":
        return n * 60.0
    if unit == "h":
        return n * 3600.0
    return n


def load(path: str) -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    cfg = Config()

    dev = raw.get("device", {})
    cfg.device.id = str(dev.get("id", ""))
    cfg.device.ip = str(dev.get("ip", ""))
    cfg.device.local_key = str(dev.get("local_key", ""))
    cfg.device.protocol = str(dev.get("protocol", cfg.device.protocol))
    cfg.device.relay_dp = str(dev.get("relay_dp", cfg.device.relay_dp))
    if "poll_interval" in dev:
        cfg.device.poll_interval = _parse_duration(dev["poll_interval"])
    if "heartbeat_interval" in dev:
        cfg.device.heartbeat_interval = _parse_duration(dev["heartbeat_interval"])

    mq = raw.get("mqtt", {})
    cfg.mqtt.host = str(mq.get("host", cfg.mqtt.host))
    cfg.mqtt.port = int(mq.get("port", cfg.mqtt.port))
    cfg.mqtt.client_id = str(mq.get("client_id", cfg.mqtt.client_id))
    cfg.mqtt.base_topic = str(mq.get("base_topic", cfg.mqtt.base_topic))
    cfg.mqtt.username = str(mq.get("username", cfg.mqtt.username))
    cfg.mqtt.password = str(mq.get("password", cfg.mqtt.password))
    if "reconnect_delay" in mq:
        cfg.mqtt.reconnect_delay = _parse_duration(mq["reconnect_delay"])

    cfg.verbose = bool(raw.get("verbose", False))

    if not cfg.device.id:
        raise ValueError("device.id is required")
    if not cfg.device.ip:
        raise ValueError("device.ip is required")
    if not cfg.device.local_key:
        raise ValueError("device.local_key is required")

    return cfg
