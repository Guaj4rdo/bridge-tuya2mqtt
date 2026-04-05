import argparse
import logging
import signal
import sys

from . import __version__
from .bridge import Bridge
from .config import load

log = logging.getLogger("tuya-bridge")

_bridge: Bridge | None = None


def _shutdown(sig, frame):
    log.info("shutting down...")
    if _bridge:
        _bridge.stop()
    sys.exit(0)


def main():
    global _bridge

    if len(sys.argv) > 1 and sys.argv[1] == "version":
        print(f"tuya-bridge {__version__}")
        sys.exit(0)

    parser = argparse.ArgumentParser(description="Tuya to MQTT bridge")
    parser.add_argument("--config", default="config.yaml", help="path to config file")
    parser.add_argument("--verbose", action="store_true", help="enable verbose logging")
    parser.add_argument("--device-ip", default="", help="override device IP")
    parser.add_argument("--device-id", default="", help="override device ID")
    parser.add_argument("--local-key", default="", help="override local key")
    parser.add_argument("--mqtt-host", default="", help="override MQTT host")
    args = parser.parse_args()

    cfg = load(args.config)

    if args.verbose:
        cfg.verbose = True
    if args.device_ip:
        cfg.device.ip = args.device_ip
    if args.device_id:
        cfg.device.id = args.device_id
    if args.local_key:
        cfg.device.local_key = args.local_key
    if args.mqtt_host:
        cfg.mqtt.host = args.mqtt_host

    level = logging.DEBUG if cfg.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Silence tinytuya's own debug logging unless verbose
    if not cfg.verbose:
        logging.getLogger("tinytuya").setLevel(logging.WARNING)

    log.info("tuya-bridge %s starting (device=%s ip=%s)", __version__, cfg.device.id, cfg.device.ip)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    _bridge = Bridge(cfg)
    _bridge.start()


if __name__ == "__main__":
    main()
