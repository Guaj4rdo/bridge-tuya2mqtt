# tuya-bridge

Bridge entre dispositivos Tuya con firmware original y un broker MQTT local. Pensado para correr en una Raspberry Pi junto a Mosquitto.

Se comunica con el dispositivo via protocolo Tuya local (TCP puerto 6668, protocolo 3.3) usando [tinytuya](https://github.com/jasonacox/tinytuya), sin depender de la nube de Tuya.

## Arquitectura

```
Dispositivo Tuya          Raspberry Pi                   Home Assistant / Node-RED / etc.
(BK7231N / DOMO-18-RF)    ┌─────────────────────┐
                           │                     │
  ◄── TCP 6668 ──────────►│   tuya-bridge        │
                           │   (este proyecto)    │
                           │                     │
                           │   ◄── MQTT ────────►│──────► Mosquitto ◄──────► Clientes MQTT
                           └─────────────────────┘
```

El bridge mantiene una conexion TCP persistente con el dispositivo, envia heartbeats periodicos para mantenerla viva, y hace polling del estado. Cuando el dispositivo reporta un cambio, lo publica por MQTT. Cuando llega un comando por MQTT, lo envia al dispositivo.

## Requisitos

- Python >= 3.9
- Un broker MQTT (Mosquitto recomendado)
- Credenciales del dispositivo Tuya (device ID, IP local, local key)

## Instalacion

```bash
git clone <repo-url> && cd bridge-tuya2mqtt
python3 -m venv venv
source venv/bin/activate
pip install .
```

## Configuracion

Editar `config.yaml`:

```yaml
device:
  id: "bf4cfbxxxxxxxxxx"       # Device ID de Tuya
  ip: "192.168.1.42"           # IP local del dispositivo
  local_key: "a1b2c3d4e5f6g7h8" # Local key (16 caracteres)
  protocol: "3.3"              # Version del protocolo
  relay_dp: "1"                # DP del relay principal
  poll_interval: 3s            # Cada cuanto consultar estado
  heartbeat_interval: 15s      # Cada cuanto enviar heartbeat

mqtt:
  host: "localhost"            # Host del broker MQTT
  port: 1883
  client_id: "tuya-bridge"
  base_topic: "tuya"           # Prefijo de los topics
  username: ""                 # Dejar vacio si no hay auth
  password: ""
  reconnect_delay: 5s

verbose: false                 # true para debug detallado
```

### Obtener las credenciales del dispositivo

El `device_id` y `local_key` se obtienen desde la plataforma Tuya IoT o con tinytuya wizard:

```bash
pip install tinytuya
python -m tinytuya wizard
```

El wizard pide las credenciales de [iot.tuya.com](https://iot.tuya.com) (crear cuenta gratuita, crear proyecto Cloud, vincular la app Smart Life/Tuya Smart via QR) y genera un JSON con id, key e IP de todos los dispositivos.

Para encontrar la IP del dispositivo tambien se puede escanear la red:

```bash
nmap -p 6668 192.168.1.0/24
```

## Uso

```bash
# Ejecutar
python -m tuya_bridge --config config.yaml

# Con verbose para debug
python -m tuya_bridge --config config.yaml --verbose

# Ver version
python -m tuya_bridge version

# Overrides por linea de comandos
python -m tuya_bridge --config config.yaml --device-ip 192.168.1.50 --mqtt-host 10.0.0.1
```

### Flags disponibles

| Flag | Default | Descripcion |
|------|---------|-------------|
| `--config` | `config.yaml` | Ruta al archivo de configuracion |
| `--verbose` | `false` | Activa logging detallado |
| `--device-ip` | - | Override de la IP del dispositivo |
| `--device-id` | - | Override del device ID |
| `--local-key` | - | Override del local key |
| `--mqtt-host` | - | Override del host MQTT |

## Topics MQTT

### Estado (publicado por el bridge)

**Topic:** `tuya/{device_id}/state`

El bridge publica el estado del dispositivo con retain activado. Cualquier cliente que se suscriba recibe el ultimo estado conocido inmediatamente.

```json
{
  "relay": true,
  "dps": {
    "1": true,
    "2": 0
  }
}
```

- `relay`: valor del DP configurado como `relay_dp` (booleano)
- `dps`: mapa completo de todos los data points reportados por el dispositivo

### Comandos (recibidos por el bridge)

**Topic:** `tuya/{device_id}/set/relay`

| Payload | Accion |
|---------|--------|
| `on`, `true`, `1` | Enciende el relay |
| `off`, `false`, `0` | Apaga el relay |
| `toggle` | Consulta el estado actual (el estado llega por el topic de state) |

Ejemplos con mosquitto_pub:

```bash
# Encender
mosquitto_pub -t "tuya/DEVICE_ID/set/relay" -m "on"

# Apagar
mosquitto_pub -t "tuya/DEVICE_ID/set/relay" -m "off"

# Consultar estado
mosquitto_pub -t "tuya/DEVICE_ID/set/relay" -m "toggle"

# Suscribirse al estado
mosquitto_sub -t "tuya/DEVICE_ID/state" -v
```

## Reconexion automatica

El bridge maneja desconexiones de forma automatica:

- **Dispositivo Tuya**: si la conexion TCP se pierde, reintenta cada 10 segundos
- **Broker MQTT**: paho-mqtt reconecta automaticamente con el delay configurado en `reconnect_delay`
- **Errores de envio**: si falla un heartbeat, poll o comando, desconecta el dispositivo para forzar reconexion limpia

## Deploy en Raspberry Pi

```bash
# Copiar archivos a la Pi
scp -r tuya_bridge/ config.yaml requirements.txt pyproject.toml pi@raspberrypi:/opt/tuya-bridge/

# En la Pi
cd /opt/tuya-bridge
python3 -m venv venv
venv/bin/pip install .

# Editar config.yaml con datos reales
nano config.yaml

# Instalar servicio systemd
sudo cp deploy/tuya-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tuya-bridge

# Ver logs
journalctl -u tuya-bridge -f
```

### Comandos utiles

```bash
sudo systemctl status tuya-bridge    # Ver estado
sudo systemctl restart tuya-bridge   # Reiniciar
sudo systemctl stop tuya-bridge      # Detener
journalctl -u tuya-bridge -n 50      # Ultimas 50 lineas de log
```

### Actualizar

```bash
cd /opt/tuya-bridge
# Copiar archivos nuevos, luego:
venv/bin/pip install .
sudo systemctl restart tuya-bridge
```

## Estructura del proyecto

```
bridge-tuya2mqtt/
├── config.yaml              # Configuracion
├── requirements.txt         # Dependencias Python
├── pyproject.toml           # Metadata del paquete
├── tuya_bridge/
│   ├── __init__.py          # Version
│   ├── __main__.py          # Entry point CLI
│   ├── config.py            # Carga y validacion de config
│   └── bridge.py            # Logica central del bridge
└── deploy/
    └── tuya-bridge.service  # Unit systemd
```

## Dependencias

| Paquete | Funcion |
|---------|---------|
| [tinytuya](https://github.com/jasonacox/tinytuya) | Protocolo Tuya local (TCP, AES-ECB, framing) |
| [paho-mqtt](https://github.com/eclipse/paho.mqtt.python) | Cliente MQTT |
| [PyYAML](https://pyyaml.org/) | Parseo de config.yaml |
