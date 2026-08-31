"""Shared helpers for the agent-widget MQTT lab (stdlib only).

Kept free of third-party imports so scripts like start-broker.sh can import
FLEET/credentials with plain python3.
"""

import hashlib
import json
import os
import random
import re
import sys
import time

# ---------------------------------------------------------------------------
# Broker connection defaults
# ---------------------------------------------------------------------------

DEFAULT_HOST = os.environ.get("MQTT_LAB_HOST", "127.0.0.1")
DEFAULT_PORT = 1883
TLS_PORT = 8883
KEEPALIVE = 10

# Test-only credentials. The broker (broker/state/passwd) is provisioned by
# scripts/start-broker.sh with these same values. Local test only.
SERVER_USER = "server"
SERVER_PASS = "srv-dev-pass"
DEVICE_PASS = "dev-test-pass"

# Default fleet: stable per-device ids (simulate MAC-derived deviceId).
FLEET = [
    "esp32s3-a1b2c3",
    "esp32s3-d4e5f6",
    "esp32s3-778899",
    "esp32s3-112233",
    "esp32s3-445566",
]

DEFAULT_AGENTS = ["claude-01", "deepseek-02", "codex-03"]
DEFAULT_START_VERSION = "2.0.0"

# ---------------------------------------------------------------------------
# Topic layout (mirrors the future production layout, see broker/mosquitto.conf)
# ---------------------------------------------------------------------------


def status_topic(agent_id: str) -> str:
    return f"agents/{agent_id}/status"


def telemetry_topic(device_id: str) -> str:
    return f"device/{device_id}/telemetry"


def events_topic(device_id: str) -> str:
    return f"device/{device_id}/events"


def ota_result_topic(device_id: str) -> str:
    return f"device/{device_id}/ota/result"


OTA_ANNOUNCE = "ota/announce"


def ota_device_topic(device_id: str) -> str:
    return f"ota/{device_id}"


def ota_group_topic(group: str) -> str:
    return f"ota/group/{group}"


def canary_group(device_id: str, buckets: int = 5) -> str:
    """Staged-rollout cohort: hash(deviceId) -> one of canary-0..canary-N.

    Matches docs/ota/11: the operator publishes to ota/group/canary-{bucket}
    for the buckets it wants to include, devices subscribe to their own bucket.
    """
    return f"canary-{canary_bucket(device_id, buckets)}"


def canary_bucket(device_id: str, buckets: int = 5) -> int:
    return int(hashlib.sha256(device_id.encode("utf-8")).hexdigest(), 16) % buckets


def canary_groups_for_percent(percent: int, fleet, buckets: int = 5) -> list:
    """Buckets that cover the requested canary percentage of the fleet."""
    included = max(1, round(len(fleet) * percent / 100.0))
    buckets_included = set()
    for dev in fleet:
        b = canary_bucket(dev, buckets)
        if len(buckets_included) < included:
            buckets_included.add(b)
    return [f"canary-{b}" for b in sorted(buckets_included)]


def version_tuple(v: str):
    return tuple(int(x) for x in v.split("."))


def version_cmp(a: str, b: str) -> int:
    return (version_tuple(a) > version_tuple(b)) - (version_tuple(a) < version_tuple(b))


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def build_agent_status(agent_id, state, seq, activity="", progress=None,
                       model="", task="", ts=None):
    p = {"v": 1, "agentId": agent_id, "ts": ts if ts is not None else int(time.time()),
         "state": state, "seq": seq}
    if activity:
        p["activity"] = activity
    if progress is not None:
        p["progress"] = int(progress)
    if model:
        p["model"] = model
    if task:
        p["task"] = task
    return p


def build_ota_announce(version, url, sha256, signature, min_version, ann_id):
    return {
        "version": version, "url": url, "sha256": sha256,
        "signature": signature, "min_version": min_version, "id": ann_id,
    }


def default_ota_url(version):
    return (f"https://github.com/agent-widget/agent-widget/releases/download/"
            f"v{version}/firmware-v{version}.bin")


def fake_sha256() -> str:
    """Deterministically-looking sha256 placeholder (lab only)."""
    return hashlib.sha256(f"lab:{time.time()}:{random.random()}".encode()).hexdigest()


def build_telemetry(device_id, online, version, cause, uptime, rssi=None,
                    heap=None, ts=None):
    return {
        "v": 1, "deviceId": device_id, "online": online, "version": version,
        "firmware": "agent-widget-esp32s3-lab",
        "rssi": rssi if rssi is not None else random.randint(-75, -45),
        "uptime": int(uptime),
        "heap": heap if heap is not None else random.randint(150_000, 260_000),
        "cause": cause, "ts": ts if ts is not None else int(time.time()),
    }


def build_event(device_id, evt, detail=None, ts=None):
    p = {"v": 1, "deviceId": device_id, "evt": evt,
         "ts": ts if ts is not None else int(time.time())}
    if detail:
        p["detail"] = detail
    return p


def build_ota_result(device_id, announce_id, from_v, to_v, outcome, ts=None):
    return {
        "v": 1, "deviceId": device_id, "announceId": announce_id,
        "from": from_v, "to": to_v, "outcome": outcome,
        "ts": ts if ts is not None else int(time.time()),
    }


# ---------------------------------------------------------------------------
# Terminal helpers
# ---------------------------------------------------------------------------

_COLORS = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m",
    "red": "\033[31m", "green": "\033[32m", "yellow": "\033[33m",
    "blue": "\033[34m", "magenta": "\033[35m", "cyan": "\033[36m",
    "grey": "\033[90m",
}
NO_COLOR = os.environ.get("NO_COLOR") == "1"

STATE_COLOR = {
    "IDLE": "blue", "RUNNING": "green", "BLOCKED": "yellow",
    "DONE": "cyan", "ERROR": "red", "OFFLINE": "grey",
}


def c(text, color):
    if NO_COLOR or not sys.stdout.isatty():
        return text
    return f"{_COLORS.get(color, '')}{text}{_COLORS['reset']}"


def log(tag, msg, color="grey"):
    print(f"{c(tag.ljust(22), color)} {msg}", flush=True)


def progress_bar(pct, width=16):
    pct = max(0, min(100, int(pct)))
    filled = round(width * pct / 100.0)
    return "█" * filled + "░" * (width - filled)


def pretty(payload):
    try:
        return json.dumps(json.loads(payload), ensure_ascii=False)
    except Exception:
        return payload
