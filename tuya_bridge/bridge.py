import json
import logging
import threading
import time

import paho.mqtt.client as mqtt
import tinytuya

from .config import Config

log = logging.getLogger("tuya-bridge")

RECONNECT_INTERVAL = 10.0


class Bridge:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._device: tinytuya.Device | None = None
        self._mqtt: mqtt.Client | None = None
        self._stop = threading.Event()
        self._connected = False
        self._send_lock = threading.Lock()
        self._recv_thread: threading.Thread | None = None

    # ── MQTT ────────────────────────────────────────────────────────

    def _state_topic(self) -> str:
        return f"{self.cfg.mqtt.base_topic}/{self.cfg.device.id}/state"

    def _set_topic(self) -> str:
        return f"{self.cfg.mqtt.base_topic}/{self.cfg.device.id}/set/#"

    def _connect_mqtt(self):
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.cfg.mqtt.client_id,
        )

        if self.cfg.mqtt.username:
            client.username_pw_set(self.cfg.mqtt.username, self.cfg.mqtt.password)

        delay = int(self.cfg.mqtt.reconnect_delay)
        client.reconnect_delay_set(min_delay=max(delay, 1), max_delay=max(delay, 1))

        client.on_connect = self._on_mqtt_connect
        client.on_message = self._on_command
        client.on_disconnect = self._on_mqtt_disconnect

        self._mqtt = client
        client.connect_async(self.cfg.mqtt.host, self.cfg.mqtt.port)
        client.loop_start()

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("[mqtt] connected to %s:%d", self.cfg.mqtt.host, self.cfg.mqtt.port)
            topic = self._set_topic()
            client.subscribe(topic)
            log.info("[mqtt] subscribed to %s", topic)
        else:
            log.error("[mqtt] connect failed rc=%s", rc)

    def _on_mqtt_disconnect(self, client, userdata, flags, rc, properties=None):
        log.warning("[mqtt] connection lost rc=%s", rc)

    # ── State publish ───────────────────────────────────────────────

    def _publish_state(self, dps: dict):
        msg: dict = {"dps": dps}
        relay_dp = self.cfg.device.relay_dp
        if relay_dp in dps:
            msg["relay"] = dps[relay_dp]
        payload = json.dumps(msg)
        topic = self._state_topic()
        self._mqtt.publish(topic, payload, qos=0, retain=True)
        if self.cfg.verbose:
            log.debug("[bridge] published to %s: %s", topic, payload)

    # ── Command handling ────────────────────────────────────────────

    def _on_command(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip().lower()

        parts = topic.split("/")
        if not parts:
            return
        command = parts[-1]

        if self.cfg.verbose:
            log.debug("[bridge] command %s = %s", command, payload)

        if command == "relay":
            self._handle_relay(payload)
        else:
            log.warning("[bridge] unknown command: %s", command)

    def _handle_relay(self, payload: str):
        dp = int(self.cfg.device.relay_dp)
        if payload in ("true", "1", "on"):
            self._send_value(dp, True)
        elif payload in ("false", "0", "off"):
            self._send_value(dp, False)
        elif payload == "toggle":
            self._send_updatedps()
        else:
            log.warning("[bridge] unknown relay payload: %s", payload)

    def _send_value(self, dp: int, value):
        with self._send_lock:
            try:
                if self._device and self._connected:
                    self._device.set_value(dp, value, nowait=True)
            except Exception as e:
                log.error("[bridge] set dp error: %s", e)
                self._mark_disconnected()

    def _send_updatedps(self):
        with self._send_lock:
            try:
                if self._device and self._connected:
                    self._device.updatedps(nowait=True)
            except Exception as e:
                log.error("[bridge] updatedps error: %s", e)
                self._mark_disconnected()

    # ── Tuya device ─────────────────────────────────────────────────

    def _connect_device(self) -> bool:
        try:
            if self._device:
                try:
                    self._device.close()
                except Exception:
                    pass

            dev = tinytuya.Device(
                dev_id=self.cfg.device.id,
                address=self.cfg.device.ip,
                local_key=self.cfg.device.local_key,
            )
            dev.set_version(float(self.cfg.device.protocol))
            dev.set_socketPersistent(True)
            dev.set_socketTimeout(5)

            status = dev.status()
            if "Error" in status:
                log.error("[tuya] connect failed: %s", status["Error"])
                return False

            self._device = dev
            self._connected = True
            log.info("[tuya] connected to %s:6668", self.cfg.device.ip)

            if "dps" in status:
                self._publish_state(status["dps"])

            self._start_receive_thread()
            return True
        except Exception as e:
            log.error("[tuya] connect error: %s", e)
            return False

    def _mark_disconnected(self):
        self._connected = False
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
        if self.cfg.verbose:
            log.debug("[tuya] disconnected from %s", self.cfg.device.ip)

    # ── Receive loop ────────────────────────────────────────────────

    def _start_receive_thread(self):
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def _receive_loop(self):
        while not self._stop.is_set() and self._connected:
            try:
                data = self._device.receive()
            except Exception as e:
                if not self._stop.is_set():
                    log.error("[tuya] receive error: %s", e)
                self._connected = False
                return

            if data is None:
                continue

            if "Error" in data:
                if not self._stop.is_set():
                    log.error("[tuya] receive error: %s", data["Error"])
                self._connected = False
                return

            if self.cfg.verbose:
                log.debug("[tuya] rx: %s", data)

            dps = data.get("dps")
            if dps and len(dps) > 0:
                self._publish_state(dps)

    # ── Timer loop ──────────────────────────────────────────────────

    def _timer_loop(self):
        now = time.monotonic()
        next_reconnect = now + RECONNECT_INTERVAL
        next_poll = now + self.cfg.device.poll_interval
        next_hb = now + self.cfg.device.heartbeat_interval

        while not self._stop.is_set():
            now = time.monotonic()
            wait = min(next_reconnect, next_poll, next_hb) - now
            if wait > 0:
                self._stop.wait(timeout=wait)
                if self._stop.is_set():
                    return

            now = time.monotonic()

            if now >= next_reconnect:
                next_reconnect = now + RECONNECT_INTERVAL
                if not self._connected:
                    log.info("[bridge] attempting device reconnect...")
                    self._connect_device()

            if now >= next_poll:
                next_poll = now + self.cfg.device.poll_interval
                if self._connected:
                    self._send_updatedps()

            if now >= next_hb:
                next_hb = now + self.cfg.device.heartbeat_interval
                if self._connected:
                    with self._send_lock:
                        try:
                            if self._device and self._connected:
                                self._device.heartbeat(nowait=True)
                        except Exception as e:
                            log.error("[bridge] heartbeat error: %s", e)
                            self._mark_disconnected()

    # ── Lifecycle ───────────────────────────────────────────────────

    def start(self):
        self._connect_mqtt()
        log.info("[bridge] connecting to device %s at %s...", self.cfg.device.id, self.cfg.device.ip)
        if not self._connect_device():
            log.warning("[bridge] initial device connect failed (will retry)")
        self._timer_loop()

    def stop(self):
        self._stop.set()
        self._connected = False
        if self._device:
            try:
                self._device.close()
            except Exception:
                pass
        if self._mqtt:
            self._mqtt.loop_stop()
            self._mqtt.disconnect()
        log.info("[bridge] stopped")
