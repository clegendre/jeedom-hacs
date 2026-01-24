"""Constants for the Jeedom integration."""

DOMAIN = "jeedom"
DEFAULT_PORT = 8080

CONF_API_KEY = "api_key"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_NAME = "name"
CONF_PROTOCOL = "protocol"
CONF_CONFIG_PATH = "config_path"
CONF_USE_JSONRPC = "use_jsonrpc"
CONF_JSONRPC_FALLBACK = "jsonrpc_fallback"
CONF_JSONRPC_URL = "jsonrpc_url"
CONF_IMPORT_MODE = "import_mode"
CONF_DOMAINS = "domains"

IMPORT_MODE_NATIVE = "native"
IMPORT_MODE_MQTT = "mqtt_entities"

SUPPORTED_DOMAINS = [
    "sensor",
    "binary_sensor",
    "switch",
    "light",
    "cover",
    "number",
    "select",
    "climate",
    "water_heater",
]

MQTT_DISCOVERY_TOPIC = "jeedom/discovery/eqLogic/#"
MQTT_EVENT_TOPIC = "jeedom/cmd/event/#"
