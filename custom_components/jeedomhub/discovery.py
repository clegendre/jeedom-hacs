"""Jeedom discovery parsing and entity/action mapping.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import re
import unicodedata
import yaml
import logging

_LOGGER = logging.getLogger(__name__)

# Hard blacklist: Z-Wave node management/status commands (not useful in HA)
NODE_MGMT_LOGICALID_SUBSTR = [
    "pingnode",
    "healnode",
    "isfailednode",
    "nodestatus",
    "refreshinfo",
    "refreshvalues",
    "refresh",
]
NODE_MGMT_NAME_SUBSTR = [
    "ping",
    "pinguer",
    "heal",
    "soigner",
    "tester",
    "test",
    "statut",
    "status",
    "node",
    "noeud",
    "noeud",
    "sante",
    "health",
]
NODE_MGMT_PROPERTY_SUBSTR = [
    "pingnode",
    "healnode",
    "isfailednode",
    "nodestatus",
]

# Hard blacklist: useless sceneId state (Z-Wave Central Scene)
SCENE_ID_LOGICALID_SUBSTR = ["sceneid"]
SCENE_ID_NAME_EXACT = {"sceneid"}
SCENE_ID_PROPERTY_SUBSTR = ["sceneid"]

# Generic defaults -> HA fields
GENERIC_DEFAULTS = {
    "POWER": {"device_class": "power", "state_class": "measurement"},
    "CONSUMPTION": {"device_class": "energy", "state_class": "total_increasing"},
    "TEMPERATURE": {"device_class": "temperature", "state_class": "measurement"},
    "HUMIDITY": {"device_class": "humidity", "state_class": "measurement"},
    "ILLUMINANCE": {"device_class": "illuminance", "state_class": "measurement", "unit_of_measurement": "lx"},
    "BATTERY": {"device_class": "battery", "state_class": "measurement", "unit_of_measurement": "%"},
    "BATTERIE": {"device_class": "battery", "state_class": "measurement", "unit_of_measurement": "%"},
    "BRIGHTNESS": {"device_class": "illuminance", "state_class": "measurement", "unit_of_measurement": "lx"},
    "THERMOSTAT_TEMPERATURE": {"device_class": "temperature", "state_class": "measurement"},
    "THERMOSTAT_SETPOINT": {"device_class": "temperature", "state_class": "measurement"},
    "THERMOSTAT_SET_SETPOINT": {"device_class": "temperature", "state_class": "measurement"},
    "FLAP_STATE": {"device_class": None, "state_class": "measurement"},
}

GENERIC_BINARY_DEFAULTS = {
    "PRESENCE": {"device_class": "presence"},
    "OPENING": {"device_class": "opening"},
}

EQ_PLATFORMS = {
    "alarm_control_panel",
    "climate",
    "cover",
    "light",
    "number",
    "select",
    "switch",
    "water_heater",
}

# Pilot wire modes (Qubino flush pilot, etc.)
PILOT_WIRE_VALUES = {0, 20, 30, 40, 50, 99, 255}
PILOT_WIRE_THRESHOLD_OFF = 10
PILOT_WIRE_THRESHOLD_FROST = 20
PILOT_WIRE_THRESHOLD_ECO = 30
PILOT_WIRE_THRESHOLD_COMFORT_2 = 40
PILOT_WIRE_THRESHOLD_COMFORT_1 = 50

KEYPAD_EQ_NAME_HINTS = ("keypad", "clavier", "rfid")
KEYPAD_ALARM_HINTS = ("alarm", "alarme", "armed", "arm")
KEYPAD_HOME_HINTS = ("home", "maison", "domicile")
KEYPAD_AWAY_HINTS = ("away", "absent", "exterieur", "exterior", "outside")
KEYPAD_DISARM_HINTS = ("disarm", "desarm", "unarm", "off", "unlock")


@dataclass
class DiscoveryConfig:
    include_all_if_no_filter: bool = True
    global_generic_whitelist: set[str] = field(default_factory=set)
    devices: list[dict[str, Any]] = field(default_factory=list)


class JeedomDiscoveryEngine:
    """Maintain eqLogic store and generate entity/action mappings."""

    def __init__(self, config: Optional[DiscoveryConfig] = None) -> None:
        self._config = config or DiscoveryConfig()
        self._eqlogic_store: Dict[int, Dict[str, Any]] = {}

    @property
    def eqlogic_store(self) -> Dict[int, Dict[str, Any]]:
        return self._eqlogic_store

    def update_eqlogic(self, data: Dict[str, Any]) -> None:
        try:
            eq_id = int(data.get("id"))
        except Exception:
            return
        self._eqlogic_store[eq_id] = data

    def generate(self) -> tuple[Dict[str, list[Dict[str, Any]]], Dict[str, Any]]:
        return generate_entity_doc(self._eqlogic_store, self._config), generate_actions(
            self._eqlogic_store, self._config
        )

    def set_config(self, config: DiscoveryConfig) -> None:
        self._config = config


def load_config(path: Optional[Path]) -> DiscoveryConfig:
    if path is None or not path.exists():
        return DiscoveryConfig()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    defaults = data.get("defaults") or {}
    devices = data.get("devices") or []
    include_all = bool(defaults.get("include_all_if_no_filter", True))
    whitelist = set(defaults.get("global_generic_whitelist") or [])
    return DiscoveryConfig(
        include_all_if_no_filter=include_all,
        global_generic_whitelist=whitelist,
        devices=devices,
    )


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[’'`]", "", value)
    value = re.sub(r"[^a-z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "item"


def is_scene_id_cmd(cmd: Dict[str, Any]) -> bool:
    lid = (cmd.get("logicalId") or "").lower()
    name = (cmd.get("name") or "").strip().lower()
    prop = (cmd.get("configuration") or {}).get("property")
    prop = (prop or "").lower() if isinstance(prop, str) else ""

    if any(s in lid for s in SCENE_ID_LOGICALID_SUBSTR):
        return True
    if name in SCENE_ID_NAME_EXACT:
        return True
    if any(s in prop for s in SCENE_ID_PROPERTY_SUBSTR):
        return True
    return False


def is_node_mgmt_cmd(cmd: Dict[str, Any]) -> bool:
    """Return True if the cmd looks like a Z-Wave node management/status command."""
    lid = (cmd.get("logicalId") or "").lower()
    name = (cmd.get("name") or "").lower()
    prop = (cmd.get("configuration") or {}).get("property")
    prop = (prop or "").lower() if isinstance(prop, str) else ""

    if any(s in lid for s in NODE_MGMT_LOGICALID_SUBSTR):
        return True
    if any(s in prop for s in NODE_MGMT_PROPERTY_SUBSTR):
        return True

    has_node_word = ("node" in name) or ("noeud" in name)
    if has_node_word:
        if any(k in name for k in ("ping", "pinguer", "heal", "soigner", "tester", "test", "statut", "status", "health", "sant")):
            return True

    if name in (
        "pinguer noeud",
        "soigner noeud",
        "tester noeud",
        "statut noeud",
    ):
        return True

    return False


def notification_113_device_class(cmd: Dict[str, Any]) -> Optional[str]:
    """Return device_class for selected Z-Wave Notification (class 113) binary commands."""

    def norm(text: Optional[str]) -> str:
        text = (text or "").lower()
        text = re.sub(r"[_\\-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    cfg = cmd.get("configuration") or {}
    zclass = str(cfg.get("class", "")).strip()
    if zclass != "113":
        return None

    lid = norm(cmd.get("logicalId"))
    name = norm(cmd.get("name"))
    prop = norm(cfg.get("property"))

    if "sensor status" in lid or "sensor status" in prop or "sensor status" in name:
        return "vibration"
    if any(k in lid for k in ("sabotage", "tamper")) or any(k in prop for k in ("sabotage", "tamper")) or any(k in name for k in ("sabotage", "tamper")):
        return "tamper"
    return None


def vibration_device_class(cmd: Dict[str, Any]) -> Optional[str]:
    """Return device_class for vibration/shock related binary commands."""

    def norm(text: Optional[str]) -> str:
        text = (text or "").lower()
        text = re.sub(r"[_\\-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    cfg = cmd.get("configuration") or {}
    lid = norm(cmd.get("logicalId"))
    name = norm(cmd.get("name"))
    prop = norm(cfg.get("property"))

    if any(k in lid for k in ("shock", "vibration", "vibrate", "impact", "choc")):
        return "vibration"
    if any(k in name for k in ("shock", "vibration", "vibrate", "impact", "choc")):
        return "vibration"
    if any(k in prop for k in ("shock", "vibration", "vibrate", "impact", "choc")):
        return "vibration"
    return None


def tamper_device_class(cmd: Dict[str, Any]) -> Optional[str]:
    """Return device_class for tamper/sabotage commands (not limited to class 113)."""

    def norm(text: Optional[str]) -> str:
        text = (text or "").lower()
        text = re.sub(r"[_\\-]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    cfg = cmd.get("configuration") or {}
    lid = norm(cmd.get("logicalId"))
    name = norm(cmd.get("name"))
    prop = norm(cfg.get("property"))

    if any(k in lid for k in ("sabotage", "tamper")):
        return "tamper"
    if any(k in name for k in ("sabotage", "tamper")):
        return "tamper"
    if any(k in prop for k in ("sabotage", "tamper")):
        return "tamper"
    return None


def is_keypad_eqlogic(eqlogic: Dict[str, Any]) -> bool:
    name_slug = slugify(eqlogic.get("name", ""))
    logical_slug = slugify(eqlogic.get("logicalId", ""))
    eqtype_slug = slugify(eqlogic.get("eqType_name", ""))
    return any(
        hint in name_slug or hint in logical_slug or hint in eqtype_slug
        for hint in KEYPAD_EQ_NAME_HINTS
    )


def is_keypad_alarm_cmd(eqlogic: Dict[str, Any], cmd: Dict[str, Any]) -> bool:
    if not is_keypad_eqlogic(eqlogic):
        return False
    name_slug = slugify(cmd.get("name") or "")
    lid_slug = slugify(cmd.get("logicalId") or "")
    if any(hint in name_slug for hint in KEYPAD_ALARM_HINTS):
        return True
    if any(hint in lid_slug for hint in KEYPAD_ALARM_HINTS):
        return True
    return False


def detect_alarm_control_panel(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect an alarm control panel from keypad-like devices."""
    if not is_keypad_eqlogic(eqlogic):
        return None

    cmds = list((eqlogic.get("cmds") or {}).values())
    state_cmd = None

    for cmd in sorted(cmds, key=lambda c: int(c.get("id", 0))):
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        if cmd.get("type") != "info":
            continue
        if (cmd.get("subType") or "").lower() not in ("binary", "numeric", "string"):
            continue
        if is_keypad_alarm_cmd(eqlogic, cmd):
            state_cmd = cmd
            break

    if not state_cmd:
        return None

    arm_home_cmd = None
    arm_away_cmd = None
    disarm_cmd = None
    arm_night_cmd = None

    for cmd in cmds:
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        if cmd.get("type") != "action":
            continue
        label = slugify(cmd.get("name") or cmd.get("logicalId") or "")
        if arm_home_cmd is None and any(hint in label for hint in KEYPAD_HOME_HINTS):
            arm_home_cmd = cmd
            continue
        if arm_away_cmd is None and any(hint in label for hint in KEYPAD_AWAY_HINTS):
            arm_away_cmd = cmd
            continue
        if disarm_cmd is None and any(hint in label for hint in KEYPAD_DISARM_HINTS):
            disarm_cmd = cmd
            continue
        if arm_night_cmd is None and "night" in label:
            arm_night_cmd = cmd

    return {
        "state_cmd": state_cmd,
        "arm_home_cmd": arm_home_cmd,
        "arm_away_cmd": arm_away_cmd,
        "arm_night_cmd": arm_night_cmd,
        "disarm_cmd": disarm_cmd,
    }


def find_rule(eqlogic: Dict[str, Any], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    eq_name = eqlogic.get("name", "")
    eq_id = eqlogic.get("id")
    for rule in config.devices:
        match = rule.get("match", {}) or {}
        if "eqlogic_id" in match and eq_id is not None and int(eq_id) == int(match["eqlogic_id"]):
            return rule
        if "eqlogic_name" in match and eq_name == match["eqlogic_name"]:
            return rule
    return None


def rule_platform(rule: Optional[Dict[str, Any]]) -> Optional[str]:
    if not rule:
        return None
    platform = str(rule.get("platform") or rule.get("device_type") or "").strip().lower()
    if platform in EQ_PLATFORMS:
        return platform
    return None


def device_slug(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]]) -> str:
    if rule and rule.get("slug"):
        return slugify(str(rule["slug"]))
    return slugify(eqlogic.get("name", f"eq_{eqlogic.get('id')}"))


def allows_cmd(rule: Optional[Dict[str, Any]], cmd: Dict[str, Any], config: DiscoveryConfig) -> bool:
    cmd_id = int(cmd.get("id"))
    generic = (cmd.get("generic_type") or "").strip().upper()
    name = (cmd.get("name") or "").strip()

    if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
        return False

    if config.global_generic_whitelist and generic and generic not in config.global_generic_whitelist:
        return False

    if rule is None:
        return True

    include = rule.get("include", {}) or {}
    cmd_ids = set(int(x) for x in (include.get("cmd_ids", []) or []))
    gen_types = set(include.get("generic_types", []) or [])
    cmd_names = set(include.get("cmd_names", []) or [])

    if not cmd_ids and not gen_types and not cmd_names:
        return config.include_all_if_no_filter

    if cmd_ids and cmd_id in cmd_ids:
        return True
    if gen_types and generic in gen_types:
        return True
    if cmd_names and name in cmd_names:
        return True
    return False


def get_override(rule: Optional[Dict[str, Any]], cmd_id: int) -> Dict[str, Any]:
    if not rule:
        return {}
    overrides = rule.get("entity_overrides") or {}
    return overrides.get(cmd_id) or overrides.get(str(cmd_id)) or {}


def _cmd_min_max(cmd: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    cfg = cmd.get("configuration") or {}
    min_v = cfg.get("minValue")
    max_v = cfg.get("maxValue")
    try:
        min_f = float(min_v) if min_v not in (None, "") else None
    except Exception:
        min_f = None
    try:
        max_f = float(max_v) if max_v not in (None, "") else None
    except Exception:
        max_f = None
    return min_f, max_f


def _get_cmd_by_id(eqlogic: Dict[str, Any], cmd_id: int) -> Optional[Dict[str, Any]]:
    for cmd in (eqlogic.get("cmds") or {}).values():
        try:
            if int(cmd.get("id")) == int(cmd_id):
                return cmd
        except Exception:
            continue
    return None


def detect_pilot_wire(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect pilot-wire heater modes (Qubino flush pilot, etc.) as a select entity."""
    cmds = list((eqlogic.get("cmds") or {}).values())

    state_cmd = None
    for c in cmds:
        if is_node_mgmt_cmd(c) or is_scene_id_cmd(c):
            continue
        if c.get("type") != "info" or c.get("subType") != "numeric":
            continue
        gt = (c.get("generic_type") or "").strip().upper()
        prop = (c.get("configuration") or {}).get("property")
        prop = str(prop or "").strip().lower()
        lid = (c.get("logicalId") or "").lower()
        if gt == "FAN_STATE" or (prop == "currentvalue" and "currentvalue" in lid):
            state_cmd = c
            break

    options = []
    has_mode_generic = False
    for c in cmds:
        if is_node_mgmt_cmd(c) or is_scene_id_cmd(c):
            continue
        if c.get("type") != "action" or c.get("subType") != "other":
            continue
        cfg = c.get("configuration") or {}
        prop = cfg.get("property")
        prop = str(prop or "").strip().lower()
        if prop != "targetvalue":
            continue
        val = cfg.get("value")
        if val is None:
            continue
        val = str(val).strip()
        if not val or val == "#slider#":
            continue
        try:
            value_i = int(float(val))
        except Exception:
            continue
        gt = (c.get("generic_type") or "").strip().upper()
        if gt.startswith("FAN_") or gt.startswith("HEATING_"):
            has_mode_generic = True
        label = (c.get("name") or c.get("logicalId") or f"mode_{value_i}").strip()
        options.append({"value": value_i, "label": label, "cmd": c, "order": int(c.get("order", 0))})

    if not state_cmd or len(options) < 3:
        return None

    known_count = sum(1 for o in options if o["value"] in PILOT_WIRE_VALUES)
    cat = eqlogic.get("category") or {}
    if known_count < 3 and not has_mode_generic and str(cat.get("heating", "0")) != "1":
        return None

    options.sort(key=lambda o: o["order"])
    seen = set()
    seen_values = set()
    filtered = []
    for o in options:
        if o["label"] in seen or o["value"] in seen_values:
            continue
        seen.add(o["label"])
        seen_values.add(o["value"])
        filtered.append(o)

    return {"state_cmd": state_cmd, "options": filtered}


def _pilot_wire_cmds(options: list[Dict[str, Any]]) -> Dict[str, Optional[Dict[str, Any]]]:
    by_value: Dict[int, Dict[str, Any]] = {}
    for opt in options:
        try:
            by_value[int(opt["value"])] = opt
        except Exception:
            continue

    def _pick(values: Tuple[int, ...], fallback: Optional[str] = None) -> Optional[Dict[str, Any]]:
        for v in values:
            if v in by_value:
                return by_value[v]
        if fallback == "min" and by_value:
            return by_value[min(by_value)]
        if fallback == "max" and by_value:
            return by_value[max(by_value)]
        return None

    return {
        "off": _pick((0, 10), "min"),
        "away": _pick((20,), None),
        "eco": _pick((30,), None),
        "comfort_2": _pick((40,), None),
        "comfort_1": _pick((50,), None),
        "comfort": _pick((255, 99, 100), "max"),
    }


def build_sensor_yaml(eqlogic: Dict[str, Any], cmd: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    if cmd.get("type") != "info":
        return None
    if is_keypad_alarm_cmd(eqlogic, cmd):
        return None
    generic = (cmd.get("generic_type") or "").strip().upper()
    if generic in GENERIC_BINARY_DEFAULTS:
        return None
    if cmd.get("subType") == "binary":
        if generic in GENERIC_BINARY_DEFAULTS:
            return None
        if notification_113_device_class(cmd):
            return None

    if not allows_cmd(rule, cmd, config):
        return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    cmd_id = int(cmd.get("id"))
    cmd_name = cmd.get("name") or cmd.get("logicalId") or f"cmd_{cmd_id}"

    unit = cmd.get("unite") or ""

    dslug = device_slug(eqlogic, rule)
    cslug = slugify(cmd_name)

    ov = get_override(rule, cmd_id)
    if ov.get("cmd_slug"):
        cslug = slugify(str(ov["cmd_slug"]))

    item: Dict[str, Any] = {
        "name": ov.get("name") or f"{eq_name} {cmd_name}",
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_{cmd_id}",
        "_cmd_id": cmd_id,
        "value_template": ov.get("value_template") or ("{{ value | float(0) }}" if cmd.get("subType") == "numeric" else None),
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}

    if ov.get("unit_of_measurement") is not None:
        if ov["unit_of_measurement"]:
            item["unit_of_measurement"] = ov["unit_of_measurement"]
    elif unit:
        item["unit_of_measurement"] = unit

    if generic in GENERIC_DEFAULTS:
        d = GENERIC_DEFAULTS[generic]
        if d.get("device_class"):
            item["device_class"] = d["device_class"]
        if d.get("state_class"):
            item["state_class"] = d["state_class"]
        if d.get("unit_of_measurement"):
            item["unit_of_measurement"] = d["unit_of_measurement"]

    for k in ("device_class", "state_class", "icon", "unit_of_measurement"):
        if ov.get(k) is not None:
            item[k] = ov[k]

    if item.get("device_class") == "illuminance":
        u = item.get("unit_of_measurement")
        if isinstance(u, str) and u.lower() == "lux":
            item["unit_of_measurement"] = "lx"

    item = {k: v for k, v in item.items() if v is not None}
    return item


def build_binary_sensor_yaml(eqlogic: Dict[str, Any], cmd: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    if cmd.get("type") != "info":
        return None
    st = (cmd.get("subType") or "").lower()
    if st not in ("binary", "numeric"):
        return None

    if not allows_cmd(rule, cmd, config):
        return None
    if is_keypad_alarm_cmd(eqlogic, cmd):
        return None

    generic = (cmd.get("generic_type") or "").strip().upper()
    cmd_name_raw = (cmd.get("name") or cmd.get("logicalId") or "").strip()
    cmd_name_slug = slugify(cmd_name_raw)

    is_generic_binary = generic in GENERIC_BINARY_DEFAULTS
    is_motion_hint = any(k in cmd_name_slug for k in ("presence", "motion", "mouvement", "occupancy"))

    notif_113_class = notification_113_device_class(cmd)
    vibration_class = vibration_device_class(cmd)
    tamper_class = tamper_device_class(cmd)

    if not (is_generic_binary or is_motion_hint or notif_113_class or vibration_class or tamper_class):
        return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    cmd_id = int(cmd.get("id"))
    cmd_name = cmd.get("name") or cmd.get("logicalId") or f"cmd_{cmd_id}"

    dslug = device_slug(eqlogic, rule)
    cslug = slugify(cmd_name)

    ov = get_override(rule, cmd_id)
    if ov.get("cmd_slug"):
        cslug = slugify(str(ov["cmd_slug"]))

    item: Dict[str, Any] = {
        "name": ov.get("name") or f"{eq_name} {cmd_name}",
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_{cmd_id}",
        "_cmd_id": cmd_id,
        "payload_on": ov.get("payload_on") or "1",
        "payload_off": ov.get("payload_off") or "0",
        "value_template": ov.get("value_template") or ("{{ '1' if (value | int(0)) > 0 else '0' }}" if st == "numeric" else None),
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}

    if notif_113_class:
        item["device_class"] = notif_113_class
    elif vibration_class:
        item["device_class"] = vibration_class
    elif tamper_class:
        item["device_class"] = tamper_class
    elif generic == "PRESENCE" or is_motion_hint:
        item["device_class"] = "motion"
    else:
        d = GENERIC_BINARY_DEFAULTS.get(generic) or {}
        if d.get("device_class"):
            item["device_class"] = d["device_class"]

    for k in ("device_class", "icon", "value_template"):
        if ov.get(k) is not None:
            item[k] = ov[k]

    item = {k: v for k, v in item.items() if v is not None}
    return item


def build_alarm_control_panel_yaml(
    eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig
) -> Optional[Dict[str, Any]]:
    detected = detect_alarm_control_panel(eqlogic)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    if rule and not allows_cmd(rule, state_cmd, config):
        return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    ov = get_override(rule, state_cmd_id)

    base_name = (rule.get("device_name") if rule else None) or eq_name
    name = ov.get("name") or base_name

    default_state_map = {
        "0": "disarmed",
        "1": "armed_away",
        "home": "disarmed",
        "away": "armed_away",
    }

    rule_state_map = None
    if rule:
        acp_cfg = rule.get("alarm_control_panel")
        if isinstance(acp_cfg, dict) and acp_cfg.get("state_map") is not None:
            rule_state_map = acp_cfg.get("state_map")
        elif rule.get("alarm_state_map") is not None:
            rule_state_map = rule.get("alarm_state_map")

    item: Dict[str, Any] = {
        "name": name,
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_alarm_control_panel",
        "state_map": ov.get("state_map") or rule_state_map or default_state_map,
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or base_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def detect_switch(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    infos = []
    actions = []

    for cmd in (eqlogic.get("cmds") or {}).values():
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        if cmd.get("type") == "info" and cmd.get("subType") == "binary":
            infos.append(cmd)
        elif cmd.get("type") == "action":
            actions.append(cmd)

    if not infos:
        return None

    on_cmd = None
    off_cmd = None

    for action in actions:
        lid = action.get("logicalId", "")
        name = action.get("name", "").lower()

        if "setvalue-true" in lid or name == "on":
            on_cmd = action
        elif "setvalue-false" in lid or name == "off":
            off_cmd = action

    if on_cmd and off_cmd:
        return {
            "state_cmd": infos[0],
            "state_cmd_id": int(infos[0].get("id")),
            "on_cmd": on_cmd,
            "off_cmd": off_cmd,
        }

    return None


def build_switch_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_switch(eqlogic)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    on_cmd = detected["on_cmd"]
    off_cmd = detected["off_cmd"]

    if rule:
        if not (allows_cmd(rule, state_cmd, config) and allows_cmd(rule, on_cmd, config) and allows_cmd(rule, off_cmd, config)):
            return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    state_slug = slugify(state_cmd.get("name") or state_cmd.get("logicalId") or "state")

    ov = get_override(rule, state_cmd_id)
    if ov.get("cmd_slug"):
        state_slug = slugify(str(ov["cmd_slug"]))

    base_name = (rule.get("device_name") if rule else None) or eq_name

    item: Dict[str, Any] = {
        "name": base_name,
        "unique_id": f"jeedom_{eq_id}_switch",
        "payload_on": "ON",
        "payload_off": "OFF",
        "state_on": "1",
        "state_off": "0",
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def _water_heater_on_mode(modes: list[str]) -> str:
    if "heat" in modes:
        return "heat"
    for mode in modes:
        if mode != "off":
            return mode
    return "on"


def build_water_heater_yaml(
    eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig
) -> Optional[Dict[str, Any]]:
    detected = detect_water_heater(eqlogic, rule, config)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    on_cmd = detected["on_cmd"]
    off_cmd = detected["off_cmd"]
    modes = [str(m).strip() for m in (detected.get("modes") or []) if str(m).strip()]
    if not modes:
        modes = ["off", "heat"]
    if "off" not in modes:
        modes = ["off"] + [m for m in modes if m != "off"]

    if rule:
        if not (allows_cmd(rule, state_cmd, config) and allows_cmd(rule, on_cmd, config) and allows_cmd(rule, off_cmd, config)):
            return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    ov = get_override(rule, state_cmd_id)

    base_name = (rule.get("device_name") if rule else None) or eq_name
    name = ov.get("name") or base_name

    on_mode = _water_heater_on_mode(modes)
    default_state_tmpl = (
        "{% set v = value | string | lower %}"
        f"{{% if v in ['on','heat','eco','boost','1','true'] or (value | int(0)) > 0 %}}{on_mode}{{% else %}}off{{% endif %}}"
    )
    mode_state_template = ov.get("mode_state_template") or ov.get("value_template") or default_state_tmpl

    item: Dict[str, Any] = {
        "name": name,
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_water_heater",
        "modes": modes,
        "mode_state_template": mode_state_template,
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def detect_water_heater(
    eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig
) -> Optional[Dict[str, Any]]:
    """Detect a simple water heater (on/off) when explicitly requested by rule."""
    if not rule:
        return None

    platform = str(rule.get("platform") or rule.get("device_type") or "").strip().lower()
    wh_cfg = rule.get("water_heater")
    if platform != "water_heater" and not isinstance(wh_cfg, dict) and wh_cfg is not True:
        return None

    eq_name = eqlogic.get("name", "")

    if wh_cfg is True or wh_cfg is None:
        wh_cfg = {}

    state_cmd = None
    on_cmd = None
    off_cmd = None

    if wh_cfg.get("state_cmd_id") is not None:
        state_cmd = _get_cmd_by_id(eqlogic, int(wh_cfg["state_cmd_id"]))
    if wh_cfg.get("on_cmd_id") is not None:
        on_cmd = _get_cmd_by_id(eqlogic, int(wh_cfg["on_cmd_id"]))
    if wh_cfg.get("off_cmd_id") is not None:
        off_cmd = _get_cmd_by_id(eqlogic, int(wh_cfg["off_cmd_id"]))

    if not on_cmd or not off_cmd or not state_cmd:
        sw = detect_switch(eqlogic)
        if sw:
            state_cmd = state_cmd or sw.get("state_cmd")
            on_cmd = on_cmd or sw.get("on_cmd")
            off_cmd = off_cmd or sw.get("off_cmd")

    if not on_cmd or not off_cmd or not state_cmd:
        actions = []
        infos = []
        for cmd in (eqlogic.get("cmds") or {}).values():
            if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
                continue
            if cmd.get("type") == "action":
                actions.append(cmd)
            elif cmd.get("type") == "info":
                infos.append(cmd)

        for action in actions:
            lid = (action.get("logicalId") or "").lower()
            name = (action.get("name") or "").strip().lower()
            gt = (action.get("generic_type") or "").strip().upper()
            if on_cmd is None and (
                "setvalue-true" in lid or name == "on" or gt in ("SWITCH_ON", "WATER_HEATER_ON")
            ):
                on_cmd = action
            if off_cmd is None and (
                "setvalue-false" in lid or name == "off" or gt in ("SWITCH_OFF", "WATER_HEATER_OFF")
            ):
                off_cmd = action

        best = None
        best_score = -1
        for info in infos:
            name = (info.get("name") or "").strip().lower()
            lid = (info.get("logicalId") or "").lower()
            st = (info.get("subType") or "").lower()
            score = 0
            if st == "binary":
                score += 3
            if any(k in name for k in ("etat", "state", "status")):
                score += 2
            if "currentvalue" in lid:
                score += 1
            if score > best_score:
                best_score = score
                best = info
        state_cmd = state_cmd or best

    if not on_cmd or not off_cmd or not state_cmd:
        _LOGGER.debug(
            "Water heater detection failed for %s: missing state/on/off cmd after heuristics",
            eq_name,
        )
        return None

    if rule and not (
        allows_cmd(rule, state_cmd, config)
        and allows_cmd(rule, on_cmd, config)
        and allows_cmd(rule, off_cmd, config)
    ):
        _LOGGER.debug(
            "Water heater detection filtered by rule for %s (state=%s on=%s off=%s)",
            eq_name,
            state_cmd.get("id") if state_cmd else None,
            on_cmd.get("id") if on_cmd else None,
            off_cmd.get("id") if off_cmd else None,
        )
        return None

    modes = wh_cfg.get("modes") or ["off", "heat"]

    return {
        "state_cmd": state_cmd,
        "on_cmd": on_cmd,
        "off_cmd": off_cmd,
        "modes": modes,
    }


def detect_cover(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cmds = list((eqlogic.get("cmds") or {}).values())

    def is_action(cmd: Dict[str, Any]) -> bool:
        return cmd.get("type") == "action"

    up = down = stop = set_pos = pos = None
    for cmd in cmds:
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        gt = (cmd.get("generic_type") or "").strip()
        lid = (cmd.get("logicalId") or "").lower()
        name = (cmd.get("name") or "").lower()

        if is_action(cmd):
            if gt == "FLAP_UP" or "-open-true" in lid or name in ("haut", "up", "open"):
                up = cmd
            elif gt == "FLAP_DOWN" or "-close-true" in lid or name in ("bas", "down", "close"):
                down = cmd
            elif gt == "FLAP_STOP" or ("-open-false" in lid and "stop" in name) or name == "stop":
                stop = cmd
            elif gt == "FLAP_SLIDER" or "#slider#" in lid or cmd.get("subType") == "slider":
                set_pos = cmd
        else:
            if gt == "FLAP_STATE" or "currentvalue" in lid or name in ("etat", "position", "state"):
                if cmd.get("subType") in ("numeric", "string"):
                    pos = cmd

    if up and down and (stop or set_pos) and pos:
        return {
            "up_cmd": up,
            "down_cmd": down,
            "stop_cmd": stop,
            "set_position_cmd": set_pos,
            "position_state_cmd": pos,
        }
    return None


def build_cover_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_cover(eqlogic)
    if not detected:
        return None

    pos_cmd = detected["position_state_cmd"]
    if rule and not allows_cmd(rule, pos_cmd, config):
        return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    pos_cmd_id = int(pos_cmd.get("id"))
    pos_slug = slugify(pos_cmd.get("name") or pos_cmd.get("logicalId") or "position")
    ov = get_override(rule, pos_cmd_id)
    if ov.get("cmd_slug"):
        pos_slug = slugify(str(ov["cmd_slug"]))

    base_name = (rule.get("device_name") if rule else None) or eq_name

    min_v, max_v = _cmd_min_max(pos_cmd)

    item: Dict[str, Any] = {
        "name": ov.get("name") or base_name,
        "unique_id": f"jeedom_{eq_id}_cover",
        "payload_open": "OPEN",
        "payload_close": "CLOSE",
        "payload_stop": "STOP",
        "_position_min": min_v,
        "_position_max": max_v,
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def detect_number(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cmds = list((eqlogic.get("cmds") or {}).values())
    slider_action = None
    state_info = None

    for cmd in cmds:
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        if cmd.get("type") == "action" and (cmd.get("subType") == "slider" or "#slider#" in (cmd.get("logicalId") or "")):
            slider_action = cmd
        if cmd.get("type") == "info" and cmd.get("subType") == "numeric":
            if state_info is None:
                state_info = cmd

    if slider_action and state_info:
        return {"set_cmd": slider_action, "state_cmd": state_info}
    return None


def build_number_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_number(eqlogic)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    set_cmd = detected["set_cmd"]

    if rule:
        if not (allows_cmd(rule, state_cmd, config) and allows_cmd(rule, set_cmd, config)):
            return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    state_slug = slugify(state_cmd.get("name") or state_cmd.get("logicalId") or "value")
    ov = get_override(rule, state_cmd_id)
    if ov.get("cmd_slug"):
        state_slug = slugify(str(ov["cmd_slug"]))

    item: Dict[str, Any] = {
        "name": ov.get("name") or f"{eq_name} Valeur",
        "unique_id": f"jeedom_{eq_id}_number",
        "value_template": "{{ value | float(0) }}",
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def detect_climate(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect a simple thermostat (climate entity)."""
    # Prefer light classification for RGBW/dimmer-style devices to avoid false climate detections.
    eq_lid = (eqlogic.get("logicalId") or "").lower()
    eq_name = (eqlogic.get("name") or "").lower()
    if "fibargroup_rgbw_controller_fgrgbw" in eq_lid or "fgrgbw" in eq_lid or "fgrgbw" in eq_name:
        return None
    cat = eqlogic.get("category") or {}
    if str(cat.get("light", "0")) == "1":
        return None

    def _setpoint_kind(cmd: Dict[str, Any]) -> str:
        def _norm(value: Any) -> str:
            if value is None:
                return ""
            return str(value).lower()

        lid = _norm(cmd.get("logicalId"))
        prop = _norm((cmd.get("configuration") or {}).get("property"))
        name = _norm(cmd.get("name"))

        if "setpoint-1" in lid or "setpoint-1" in prop:
            return "hot"
        if "setpoint-2" in lid or "setpoint-2" in prop:
            return "cold"
        if "setpoint-10" in lid or "setpoint-10" in prop:
            return "auto"

        if any(k in name for k in ("chaud", "hot", "heat")):
            return "hot"
        if any(k in name for k in ("froid", "cold", "cool")):
            return "cold"
        if "auto" in name:
            return "auto"
        return ""

    cmds = list((eqlogic.get("cmds") or {}).values())

    current_temp = None
    target_temp_states: Dict[str, Dict[str, Any]] = {}
    set_temp_cmds: Dict[str, Dict[str, Any]] = {}
    setpoint_kind = None

    for cmd in cmds:
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        gt = (cmd.get("generic_type") or "").strip().upper()
        lid = (cmd.get("logicalId") or "").lower()
        name = (cmd.get("name") or "").lower()
        kind = _setpoint_kind(cmd)

        if cmd.get("type") == "info" and cmd.get("subType") == "numeric":
            if gt == "THERMOSTAT_TEMPERATURE":
                current_temp = cmd
            elif kind:
                target_temp_states[kind] = cmd
            elif gt == "THERMOSTAT_SETPOINT":
                target_temp_states.setdefault("auto", cmd)

        if cmd.get("type") == "action":
            if cmd.get("subType") == "slider" or "#slider#" in lid:
                if kind:
                    set_temp_cmds[kind] = cmd
                elif gt == "THERMOSTAT_SET_SETPOINT" or gt == "THERMOSTAT_SETPOINT" or "consigne" in name or "setpoint" in name:
                    set_temp_cmds.setdefault("auto", cmd)

    preferred = ("hot", "auto", "cold")
    for key in preferred:
        if key in set_temp_cmds:
            setpoint_kind = key
            break
    if not setpoint_kind:
        return None

    set_temp_cmd = set_temp_cmds[setpoint_kind]
    target_temp_state = target_temp_states.get(setpoint_kind) or target_temp_states.get("auto")

    return {
        "current_temp_cmd": current_temp,
        "target_temp_state_cmd": target_temp_state,
        "set_temp_cmd": set_temp_cmd,
        "set_temp_cmds": set_temp_cmds,
        "target_temp_state_cmds": target_temp_states,
        "setpoint_kind": setpoint_kind,
    }


def detect_light(eqlogic: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Detect a light entity."""
    cmds = list((eqlogic.get("cmds") or {}).values())

    try:
        if detect_climate(eqlogic) is not None:
            return None
    except Exception:
        pass

    try:
        if detect_cover(eqlogic) is not None:
            return None
    except Exception:
        pass

    cat = eqlogic.get("category") or {}
    if (str(cat.get("opening", "0")) == "1" or str(cat.get("automatism", "0")) == "1") and str(cat.get("light", "0")) != "1":
        return None

    actions = []
    infos = []
    for cmd in cmds:
        if is_node_mgmt_cmd(cmd) or is_scene_id_cmd(cmd):
            continue
        if cmd.get("type") == "action":
            actions.append(cmd)
        elif cmd.get("type") == "info":
            infos.append(cmd)

    def _norm_text(value: Any) -> str:
        text = str(value or "").lower()
        text = unicodedata.normalize("NFKD", text)
        text = "".join(ch for ch in text if not unicodedata.combining(ch))
        text = re.sub(r"[_\\-]+", " ", text)
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _color_channel(cmd: Dict[str, Any]) -> Optional[str]:
        gt = (cmd.get("generic_type") or "").strip().upper()
        if "RED" in gt:
            return "red"
        if "GREEN" in gt:
            return "green"
        if "BLUE" in gt:
            return "blue"
        if "WHITE" in gt or gt.endswith("_W"):
            return "white"

        lid = _norm_text(cmd.get("logicalId"))
        name = _norm_text(cmd.get("name"))
        prop = _norm_text((cmd.get("configuration") or {}).get("property"))
        text = " ".join(t for t in (lid, name, prop) if t)

        if re.search(r"\b(red|rouge)\b", text):
            return "red"
        if re.search(r"\b(green|vert)\b", text):
            return "green"
        if re.search(r"\b(blue|bleu)\b", text):
            return "blue"
        if re.search(r"\b(white|blanc)\b", text):
            return "white"

        tokens = set(text.split())
        if {"rgb", "rgbw", "color", "couleur"} & tokens:
            if "r" in tokens:
                return "red"
            if "g" in tokens:
                return "green"
            if "b" in tokens:
                return "blue"
            if "w" in tokens:
                return "white"

        if re.search(r"\bcolor\s*[rgbw]\b", text):
            if "color r" in text:
                return "red"
            if "color g" in text:
                return "green"
            if "color b" in text:
                return "blue"
            if "color w" in text:
                return "white"
        return None

    on_cmd = None
    off_cmd = None
    brightness_set = None
    color_set_cmds: Dict[str, Dict[str, Any]] = {}
    color_state_cmds: Dict[str, Dict[str, Any]] = {}
    state_bin = None

    for action in actions:
        lid = (action.get("logicalId") or "").lower()
        name = (action.get("name") or "").strip().lower()
        gt = (action.get("generic_type") or "").strip()

        if "setvalue-true" in lid or name == "on" or gt in ("LIGHT_ON", "SWITCH_ON"):
            on_cmd = action
        elif "setvalue-false" in lid or name == "off" or gt in ("LIGHT_OFF", "SWITCH_OFF"):
            off_cmd = action

        if action.get("subType") == "slider" or "#slider#" in lid:
            channel = _color_channel(action)
            if channel and channel not in color_set_cmds:
                color_set_cmds[channel] = action

    for info in infos:
        lid = (info.get("logicalId") or "").lower()
        name = (info.get("name") or "").strip().lower()

        if state_bin is None and info.get("subType") == "binary":
            if name in ("etat", "state", "on", "off") or "currentvalue" in lid:
                state_bin = info

        if info.get("subType") == "numeric":
            channel = _color_channel(info)
            if channel and channel not in color_state_cmds:
                color_state_cmds[channel] = info

    for action in actions:
        if brightness_set is not None:
            break
        if action in color_set_cmds.values():
            continue
        lid = (action.get("logicalId") or "").lower()
        name = (action.get("name") or "").strip().lower()
        gt = (action.get("generic_type") or "").strip()
        if action.get("subType") == "slider" or "#slider#" in lid or gt in ("LIGHT_SLIDER", "DIMMER"):
            brightness_set = action
        elif any(k in name for k in ("brightness", "dimmer", "level", "niveau", "intensite", "luminosite")):
            brightness_set = action

    brightness_state = None
    for info in infos:
        if brightness_state is not None:
            break
        if info.get("subType") != "numeric":
            continue
        if info in color_state_cmds.values():
            continue
        lid = (info.get("logicalId") or "").lower()
        name = (info.get("name") or "").strip().lower()
        if "currentvalue" in lid or name in ("niveau", "brightness", "dimmer", "level", "valeur", "intensite", "luminosite"):
            brightness_state = info

    cat = eqlogic.get("category") or {}
    is_marked_light = str(cat.get("light", "0")) == "1"

    has_light_generic = any(
        (c.get("generic_type") or "").strip() in ("LIGHT_ON", "LIGHT_OFF", "LIGHT_SLIDER", "DIMMER")
        for c in cmds
        if isinstance(c, dict)
    )

    has_rgb = all(k in color_set_cmds for k in ("red", "green", "blue"))

    if has_rgb or brightness_set or is_marked_light or has_light_generic:
        if has_rgb or (on_cmd and off_cmd) or brightness_set:
            return {
                "on_cmd": on_cmd,
                "off_cmd": off_cmd,
                "brightness_set_cmd": brightness_set,
                "state_cmd": state_bin,
                "brightness_state_cmd": brightness_state,
                "color_set_cmds": color_set_cmds,
                "color_state_cmds": color_state_cmds,
            }

    return None


def build_light_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_light(eqlogic)
    if not detected:
        return None

    if rule:
        for key in ("on_cmd", "off_cmd", "brightness_set_cmd", "state_cmd", "brightness_state_cmd"):
            cmd = detected.get(key)
            if cmd is not None and not allows_cmd(rule, cmd, config):
                return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    base_name = (rule.get("device_name") if rule else None) or eq_name

    item: Dict[str, Any] = {
        "name": base_name,
        "unique_id": f"jeedom_{eq_id}_light",
        "payload_on": "ON",
        "payload_off": "OFF",
        "optimistic": True,
        "device": {
            "identifiers": [f"jeedom_{dslug}"],
            "name": base_name,
        },
    }

    st_cmd = detected.get("state_cmd")
    if st_cmd is not None:
        st_cmd_id = int(st_cmd.get("id"))
        ov = get_override(rule, st_cmd_id)
        item["name"] = ov.get("name") or base_name
        item["device"] = {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or base_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        }
        item["device"] = {k: v for k, v in item["device"].items() if v}
        item.pop("optimistic", None)

    if detected.get("brightness_set_cmd") is not None:
        item["brightness_scale"] = 255

    item = {k: v for k, v in item.items() if v is not None}
    return item


def build_select_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_pilot_wire(eqlogic)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    if rule and not allows_cmd(rule, state_cmd, config):
        return None

    options = []
    for opt in detected["options"]:
        cmd = opt["cmd"]
        if rule and not allows_cmd(rule, cmd, config):
            continue
        options.append(opt)

    if len(options) < 2:
        return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    ov = get_override(rule, state_cmd_id)

    base_name = (rule.get("device_name") if rule else None) or eq_name
    name = ov.get("name") or f"{base_name} Mode"

    options_map = {int(opt["value"]): str(opt["label"]) for opt in options}
    if len(options_map) < 2:
        return None

    item: Dict[str, Any] = {
        "name": name,
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_select",
        "options": list(options_map.values()),
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    if ov.get("icon") is not None:
        item["icon"] = ov["icon"]

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def build_pilot_climate_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_pilot_wire(eqlogic)
    if not detected:
        return None

    state_cmd = detected["state_cmd"]
    if rule and not allows_cmd(rule, state_cmd, config):
        return None

    options = []
    for opt in detected["options"]:
        cmd = opt["cmd"]
        if rule and not allows_cmd(rule, cmd, config):
            continue
        options.append(opt)

    if not options:
        return None

    pilot_cmds = _pilot_wire_cmds(options)
    if not pilot_cmds.get("off") or not pilot_cmds.get("comfort"):
        return None

    additional_modes = bool(pilot_cmds.get("comfort_1") and pilot_cmds.get("comfort_2"))

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    state_cmd_id = int(state_cmd.get("id"))
    ov = get_override(rule, state_cmd_id)

    base_name = (rule.get("device_name") if rule else None) or eq_name
    name = ov.get("name") or base_name

    preset_modes = ["comfort"]
    if additional_modes:
        preset_modes.extend(["comfort-1", "comfort-2"])
    preset_modes.extend(["eco", "away"])

    item: Dict[str, Any] = {
        "name": name,
        "unique_id": ov.get("unique_id") or f"jeedom_{eq_id}_pilot_climate",
        "modes": ["heat", "off"],
        "preset_modes": preset_modes,
        "device": {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or (rule.get("device_name") if rule else None) or eq_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        },
    }

    temp_cmd = None
    for cmd in (eqlogic.get("cmds") or {}).values():
        if cmd.get("type") != "info" or cmd.get("subType") != "numeric":
            continue
        if (cmd.get("generic_type") or "").strip().upper() == "TEMPERATURE":
            temp_cmd = cmd
            break
    if temp_cmd is not None and (not rule or allows_cmd(rule, temp_cmd, config)):
        item["_current_temperature_cmd_id"] = int(temp_cmd.get("id"))

    if ov.get("icon") is not None:
        item["icon"] = ov["icon"]

    item["device"] = {k: v for k, v in item["device"].items() if v}
    item = {k: v for k, v in item.items() if v is not None}
    return item


def build_climate_yaml(eqlogic: Dict[str, Any], rule: Optional[Dict[str, Any]], config: DiscoveryConfig) -> Optional[Dict[str, Any]]:
    detected = detect_climate(eqlogic)
    if not detected:
        return None

    if rule:
        for key in ("current_temp_cmd", "target_temp_state_cmd", "set_temp_cmd"):
            cmd = detected.get(key)
            if cmd is not None and not allows_cmd(rule, cmd, config):
                return None

    eq_id = int(eqlogic.get("id"))
    eq_name = eqlogic.get("name", f"Jeedom {eq_id}")
    dslug = device_slug(eqlogic, rule)

    base_name = (rule.get("device_name") if rule else None) or eq_name

    item: Dict[str, Any] = {
        "name": base_name,
        "unique_id": f"jeedom_{eq_id}_climate",
        "modes": ["off", "heat"],
        "device": {
            "identifiers": [f"jeedom_{dslug}"],
            "name": base_name,
        },
        "min_temp": 5,
        "max_temp": 30,
        "temp_step": 0.5,
    }

    ct_cmd = detected.get("current_temp_cmd")
    if ct_cmd is not None:
        ct_cmd_id = int(ct_cmd.get("id"))
        ov = get_override(rule, ct_cmd_id)
        item["device"] = {
            "identifiers": [ov.get("device_identifier") or f"jeedom_{dslug}"],
            "name": ov.get("device_name") or base_name,
            "manufacturer": ov.get("manufacturer"),
            "model": ov.get("model"),
        }
        item["device"] = {k: v for k, v in item["device"].items() if v}

    item = {k: v for k, v in item.items() if v is not None}
    return item


def generate_entity_doc(eqlogic_store: Dict[int, Dict[str, Any]], config: DiscoveryConfig) -> Dict[str, list[Dict[str, Any]]]:
    sensors: list[Dict[str, Any]] = []
    binary_sensors: list[Dict[str, Any]] = []
    alarm_control_panels: list[Dict[str, Any]] = []
    lights: list[Dict[str, Any]] = []
    switches: list[Dict[str, Any]] = []
    water_heaters: list[Dict[str, Any]] = []
    covers: list[Dict[str, Any]] = []
    numbers: list[Dict[str, Any]] = []
    climates: list[Dict[str, Any]] = []
    selects: list[Dict[str, Any]] = []

    for eq_id in sorted(eqlogic_store.keys()):
        eq = eqlogic_store[eq_id]
        rule = find_rule(eq, config)
        cmds = (eq.get("cmds") or {}).values()
        for cmd in sorted(cmds, key=lambda c: int(c.get("id", 0))):
            bs = build_binary_sensor_yaml(eq, cmd, rule, config)
            if bs:
                binary_sensors.append(bs)
                continue
            sensor = build_sensor_yaml(eq, cmd, rule, config)
            if sensor:
                sensors.append(sensor)

        forced = rule_platform(rule)

        if forced == "alarm_control_panel":
            acp = build_alarm_control_panel_yaml(eq, rule, config)
            if acp:
                alarm_control_panels.append(acp)
        elif forced == "climate":
            pcl = build_pilot_climate_yaml(eq, rule, config)
            if pcl:
                climates.append(pcl)
            else:
                climate = build_climate_yaml(eq, rule, config)
                if climate:
                    climates.append(climate)
        elif forced == "water_heater":
            wh = build_water_heater_yaml(eq, rule, config)
            if wh:
                water_heaters.append(wh)
        elif forced == "cover":
            cover = build_cover_yaml(eq, rule, config)
            if cover:
                covers.append(cover)
        elif forced == "light":
            light = build_light_yaml(eq, rule, config)
            if light:
                lights.append(light)
        elif forced == "switch":
            switch = build_switch_yaml(eq, rule, config)
            if switch:
                switches.append(switch)
        elif forced == "number":
            number = build_number_yaml(eq, rule, config)
            if number:
                numbers.append(number)
        elif forced == "select":
            select = build_select_yaml(eq, rule, config)
            if select:
                selects.append(select)
        else:
            acp = build_alarm_control_panel_yaml(eq, rule, config)
            if acp:
                alarm_control_panels.append(acp)

            has_climate = False
            pcl = build_pilot_climate_yaml(eq, rule, config)
            if pcl:
                climates.append(pcl)
                has_climate = True
            if not has_climate:
                climate = build_climate_yaml(eq, rule, config)
                if climate:
                    climates.append(climate)
                    has_climate = True

            has_water_heater = False
            wh = build_water_heater_yaml(eq, rule, config)
            if wh:
                water_heaters.append(wh)
                has_water_heater = True

            has_cover = False
            cover = build_cover_yaml(eq, rule, config)
            if cover:
                covers.append(cover)
                has_cover = True

            has_light = False
            if not has_cover and not has_climate and not has_water_heater:
                light = build_light_yaml(eq, rule, config)
                if light:
                    lights.append(light)
                    has_light = True

            if not has_light and not has_cover and not has_climate and not has_water_heater:
                switch = build_switch_yaml(eq, rule, config)
                if switch:
                    switches.append(switch)

            number = build_number_yaml(eq, rule, config)
            if number:
                numbers.append(number)

            select = build_select_yaml(eq, rule, config)
            if select:
                selects.append(select)

    return {
        "sensor": sensors,
        "binary_sensor": binary_sensors,
        "alarm_control_panel": alarm_control_panels,
        "climate": climates,
        "light": lights,
        "switch": switches,
        "water_heater": water_heaters,
        "cover": covers,
        "number": numbers,
        "select": selects,
    }


def generate_actions(eqlogic_store: Dict[int, Dict[str, Any]], config: DiscoveryConfig) -> Dict[str, Any]:
    actions: Dict[str, Any] = {
        "alarm_control_panel": {},
        "light": {},
        "switch": {},
        "water_heater": {},
        "cover": {},
        "number": {},
        "select": {},
        "pilot_climate": {},
        "button": {},
        "climate": {},
    }

    def _cmd_value(cmd: Dict[str, Any]) -> Optional[str]:
        cfg = cmd.get("configuration") or {}
        val = cfg.get("value")
        if val is None:
            return None
        val = str(val).strip()
        if not val or val == "#slider#":
            return None
        return val

    def _cmd_range(cmd: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
        cfg = cmd.get("configuration") or {}
        min_v = cfg.get("minValue")
        max_v = cfg.get("maxValue")
        try:
            min_i = int(float(min_v)) if min_v not in (None, "") else None
        except Exception:
            min_i = None
        try:
            max_i = int(float(max_v)) if max_v not in (None, "") else None
        except Exception:
            max_i = None
        return min_i, max_i

    def _cmd_property(cmd: Dict[str, Any]) -> Optional[str]:
        cfg = cmd.get("configuration") or {}
        prop = cfg.get("property")
        if prop is None:
            return None
        prop = str(prop).strip()
        return prop or None

    for eq_id in sorted(eqlogic_store.keys()):
        eq = eqlogic_store[eq_id]
        rule = find_rule(eq, config)
        forced = rule_platform(rule)

        allow_light = forced is None or forced == "light"
        allow_switch = forced is None or forced == "switch"
        allow_water_heater = forced is None or forced == "water_heater"
        allow_cover = forced is None or forced == "cover"
        allow_number = forced is None or forced == "number"
        allow_select = forced is None or forced == "select"
        allow_alarm_panel = forced is None or forced == "alarm_control_panel"
        allow_climate = forced is None or forced == "climate"
        allow_pilot = forced is None or forced == "climate"

        lt = detect_light(eq) if allow_light else None
        if lt:
            ok = True
            if rule:
                for key in ("on_cmd", "off_cmd", "brightness_set_cmd", "state_cmd", "brightness_state_cmd"):
                    cmd = lt.get(key)
                    if cmd is not None and not allows_cmd(rule, cmd, config):
                        ok = False
                        break
                if ok:
                    for cmd in (lt.get("color_set_cmds") or {}).values():
                        if cmd is not None and not allows_cmd(rule, cmd, config):
                            ok = False
                            break
                if ok:
                    for cmd in (lt.get("color_state_cmds") or {}).values():
                        if cmd is not None and not allows_cmd(rule, cmd, config):
                            ok = False
                            break
            if ok:
                payload: Dict[str, Any] = {}
                if lt.get("on_cmd") is not None:
                    payload["on_cmd_id"] = int(lt["on_cmd"].get("id"))
                if lt.get("off_cmd") is not None:
                    payload["off_cmd_id"] = int(lt["off_cmd"].get("id"))
                if lt.get("brightness_set_cmd") is not None:
                    payload["brightness_cmd_id"] = int(lt["brightness_set_cmd"].get("id"))
                    bmin, bmax = _cmd_range(lt["brightness_set_cmd"])
                    if bmin is not None:
                        payload["brightness_min"] = bmin
                    if bmax is not None:
                        payload["brightness_max"] = bmax
                        payload["default_on_brightness"] = bmax
                    else:
                        payload["brightness_max"] = 99
                        payload["default_on_brightness"] = 99
                if lt.get("state_cmd") is not None:
                    payload["state_cmd_id"] = int(lt["state_cmd"].get("id"))
                if lt.get("brightness_state_cmd") is not None:
                    payload["brightness_state_cmd_id"] = int(lt["brightness_state_cmd"].get("id"))
                for channel in ("red", "green", "blue", "white"):
                    cmd = (lt.get("color_set_cmds") or {}).get(channel)
                    if cmd is not None:
                        payload[f"{channel}_cmd_id"] = int(cmd.get("id"))
                        cmin, cmax = _cmd_range(cmd)
                        if cmin is not None:
                            payload[f"{channel}_min"] = cmin
                        if cmax is not None:
                            payload[f"{channel}_max"] = cmax
                    cmd = (lt.get("color_state_cmds") or {}).get(channel)
                    if cmd is not None:
                        payload[f"{channel}_state_cmd_id"] = int(cmd.get("id"))
                actions["light"][f"jeedom_{eq_id}"] = payload

        wh = detect_water_heater(eq, rule, config) if allow_water_heater else None
        if wh:
            actions["water_heater"][f"jeedom_{eq_id}"] = {
                "state_cmd_id": int(wh["state_cmd"].get("id")),
                "on_cmd_id": int(wh["on_cmd"].get("id")),
                "off_cmd_id": int(wh["off_cmd"].get("id")),
            }

        acp = detect_alarm_control_panel(eq) if allow_alarm_panel else None
        if acp:
            state_cmd = acp["state_cmd"]
            if not rule or allows_cmd(rule, state_cmd, config):
                payload: Dict[str, Any] = {"state_cmd_id": int(state_cmd.get("id"))}
                if acp.get("arm_home_cmd") is not None and (not rule or allows_cmd(rule, acp["arm_home_cmd"], config)):
                    payload["arm_home_cmd_id"] = int(acp["arm_home_cmd"].get("id"))
                if acp.get("arm_away_cmd") is not None and (not rule or allows_cmd(rule, acp["arm_away_cmd"], config)):
                    payload["arm_away_cmd_id"] = int(acp["arm_away_cmd"].get("id"))
                if acp.get("arm_night_cmd") is not None and (not rule or allows_cmd(rule, acp["arm_night_cmd"], config)):
                    payload["arm_night_cmd_id"] = int(acp["arm_night_cmd"].get("id"))
                if acp.get("disarm_cmd") is not None and (not rule or allows_cmd(rule, acp["disarm_cmd"], config)):
                    payload["disarm_cmd_id"] = int(acp["disarm_cmd"].get("id"))
                actions["alarm_control_panel"][f"jeedom_{eq_id}"] = payload

        if allow_switch and not lt and not wh:
            sw = detect_switch(eq)
            if sw:
                state_cmd = sw["state_cmd"]
                on_cmd = sw["on_cmd"]
                off_cmd = sw["off_cmd"]
                if not rule or (allows_cmd(rule, state_cmd, config) and allows_cmd(rule, on_cmd, config) and allows_cmd(rule, off_cmd, config)):
                    actions["switch"][f"jeedom_{eq_id}"] = {
                        "state_cmd_id": int(state_cmd.get("id")),
                        "on_cmd_id": int(on_cmd.get("id")),
                        "off_cmd_id": int(off_cmd.get("id")),
                    }

        cv = detect_cover(eq) if allow_cover else None
        if cv:
            pos = cv["position_state_cmd"]
            up = cv["up_cmd"]
            down = cv["down_cmd"]
            stop = cv.get("stop_cmd")
            setp = cv.get("set_position_cmd")
            if not rule or (allows_cmd(rule, pos, config) and allows_cmd(rule, up, config) and allows_cmd(rule, down, config) and (not stop or allows_cmd(rule, stop, config)) and (not setp or allows_cmd(rule, setp, config))):
                payload = {
                    "position_state_cmd_id": int(pos.get("id")),
                    "open_cmd_id": int(up.get("id")),
                    "close_cmd_id": int(down.get("id")),
                }
                ov = _cmd_value(up)
                if ov is not None:
                    payload["open_cmd_value"] = ov
                cvv = _cmd_value(down)
                if cvv is not None:
                    payload["close_cmd_value"] = cvv
                if stop:
                    payload["stop_cmd_id"] = int(stop.get("id"))
                    sv = _cmd_value(stop)
                    if sv is not None:
                        payload["stop_cmd_value"] = sv
                if setp:
                    payload["set_position_cmd_id"] = int(setp.get("id"))
                    smin, smax = _cmd_range(setp)
                    if smin is not None:
                        payload["set_position_min"] = smin
                    if smax is not None:
                        payload["set_position_max"] = smax
                    sprop = _cmd_property(setp)
                    if sprop is not None:
                        payload["set_position_property"] = sprop
                actions["cover"][f"jeedom_{eq_id}"] = payload

        nb = detect_number(eq) if allow_number else None
        if nb:
            state_cmd = nb["state_cmd"]
            set_cmd = nb["set_cmd"]
            if not rule or (allows_cmd(rule, state_cmd, config) and allows_cmd(rule, set_cmd, config)):
                actions["number"][f"jeedom_{eq_id}"] = {
                    "state_cmd_id": int(state_cmd.get("id")),
                    "set_cmd_id": int(set_cmd.get("id")),
                }

        cl = detect_climate(eq) if allow_climate else None
        if cl:
            ok = True
            if rule:
                for key in ("current_temp_cmd", "target_temp_state_cmd", "set_temp_cmd"):
                    cmd = cl.get(key)
                    if cmd is not None and not allows_cmd(rule, cmd, config):
                        ok = False
                        break
            if ok:
                payload: Dict[str, Any] = {
                    "set_temperature_cmd_id": int(cl["set_temp_cmd"].get("id")),
                }
                if cl.get("setpoint_kind"):
                    payload["setpoint_kind"] = cl["setpoint_kind"]
                for kind, cmd in (cl.get("set_temp_cmds") or {}).items():
                    payload[f"set_temperature_cmd_id_{kind}"] = int(cmd.get("id"))
                if cl.get("current_temp_cmd") is not None:
                    payload["current_temperature_cmd_id"] = int(cl["current_temp_cmd"].get("id"))
                if cl.get("target_temp_state_cmd") is not None:
                    payload["temperature_state_cmd_id"] = int(cl["target_temp_state_cmd"].get("id"))
                for kind, cmd in (cl.get("target_temp_state_cmds") or {}).items():
                    payload[f"temperature_state_cmd_id_{kind}"] = int(cmd.get("id"))
                actions["climate"][f"jeedom_{eq_id}"] = payload

        sel = detect_pilot_wire(eq) if (allow_select or allow_pilot) else None
        if sel:
            if rule and not allows_cmd(rule, sel["state_cmd"], config):
                sel = None
            if sel:
                options = []
                options_map: Dict[str, Any] = {}
                for opt in sel["options"]:
                    cmd = opt["cmd"]
                    if rule and not allows_cmd(rule, cmd, config):
                        continue
                    options.append(opt)
                    payload = {"cmd_id": int(cmd.get("id"))}
                    val = _cmd_value(cmd)
                    if val is not None:
                        payload["value"] = val
                    options_map[str(opt["label"])] = payload
                if allow_select and len(options_map) >= 2:
                    actions["select"][f"jeedom_{eq_id}"] = {
                        "state_cmd_id": int(sel["state_cmd"].get("id")),
                        "options": options_map,
                    }

                if allow_pilot:
                    pilot_cmds = _pilot_wire_cmds(options)
                    if pilot_cmds.get("off") and pilot_cmds.get("comfort"):
                        mode_map: Dict[str, Any] = {}
                        preset_map: Dict[str, Any] = {}

                        def _add_cmd(target: Dict[str, Any], key: str, opt: Optional[Dict[str, Any]]):
                            if not opt:
                                return
                            cmd = opt["cmd"]
                            if rule and not allows_cmd(rule, cmd, config):
                                return
                            payload = {"cmd_id": int(cmd.get("id"))}
                            val = _cmd_value(cmd)
                            if val is not None:
                                payload["value"] = val
                            target[key] = payload

                        _add_cmd(mode_map, "heat", pilot_cmds.get("comfort"))
                        _add_cmd(mode_map, "off", pilot_cmds.get("off"))

                        _add_cmd(preset_map, "comfort", pilot_cmds.get("comfort"))
                        _add_cmd(preset_map, "eco", pilot_cmds.get("eco"))
                        _add_cmd(preset_map, "away", pilot_cmds.get("away"))
                        _add_cmd(preset_map, "comfort-1", pilot_cmds.get("comfort_1"))
                        _add_cmd(preset_map, "comfort-2", pilot_cmds.get("comfort_2"))
                        _add_cmd(preset_map, "none", pilot_cmds.get("off"))

                        if mode_map and preset_map:
                            actions["pilot_climate"][f"jeedom_{eq_id}"] = {
                                "state_cmd_id": int(sel["state_cmd"].get("id")),
                                "mode": mode_map,
                                "preset": preset_map,
                            }

    actions = {k: v for k, v in actions.items() if v}
    return actions


__all__ = [
    "DiscoveryConfig",
    "JeedomDiscoveryEngine",
    "load_config",
    "PILOT_WIRE_THRESHOLD_OFF",
    "PILOT_WIRE_THRESHOLD_FROST",
    "PILOT_WIRE_THRESHOLD_ECO",
    "PILOT_WIRE_THRESHOLD_COMFORT_2",
    "PILOT_WIRE_THRESHOLD_COMFORT_1",
]
