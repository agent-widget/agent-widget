#!/usr/bin/env python3
"""Server-side OTA notification publisher for the agent-widget MQTT lab.

Implements the rollout strategies from docs/ota/11-ota-notification-mqtt.md:
  - broadcast : ota/announce, retained  -> every device
  - device    : ota/{deviceId}          -> one device
  - group     : ota/group/{group}       -> named cohort (stable/beta/...)
  - canary    : ota/group/canary-{b}    -> hash(deviceId) buckets for a % of fleet

MQTT carries metadata only; the firmware binary is downloaded over HTTPS
(simulated by the device). The payload follows ota-announce-v1.schema.json.

Examples:
  python3 ota_pub.py --target broadcast --version 3.3.0
  python3 ota_pub.py --target canary --percent 40 --version 3.1.0
  python3 ota_pub.py --target group --group stable --version 3.1.0
  python3 ota_pub.py --target device --device-id esp32s3-112233 --version 3.2.0
  python3 ota_pub.py --target broadcast --version 3.0.0 --min-version 3.3.0  # recall guard demo
"""

import argparse
import datetime
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt  # noqa: E402

from common import (  # noqa: E402
    FLEET, KEEPALIVE, OTA_ANNOUNCE, SERVER_PASS, SERVER_USER, canary_bucket,
    canary_groups_for_percent, default_ota_url, log, ota_device_topic,
    ota_group_topic, build_ota_announce, c,
)

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except Exception:
    _HAS_JSONSCHEMA = False


def _load_schema(name):
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "contracts", name)
    with open(p) as f:
        return json.load(f)


SCHEMA = _load_schema("ota-announce-v1.schema.json")


def make_announce(args, ann_id):
    if not args.sha256:
        args.sha256 = hashlib.sha256(f"firmware-{args.version}".encode()).hexdigest()
    signature = "TUFHLVJBQ0lOR1RFTkRVTVNJR05BVFVSRUxBQk9OTFk="  # placeholder base64
    payload = build_ota_announce(
        version=args.version,
        url=args.url or default_ota_url(args.version),
        sha256=args.sha256,
        signature=signature,
        min_version=args.min_version,
        ann_id=ann_id,
    )
    if _HAS_JSONSCHEMA:
        jsonschema.validate(payload, SCHEMA)
    return payload


def main():
    ap = argparse.ArgumentParser(description="OTA announce publisher (MQTT lab)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--ca",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "broker", "certs", "ca.crt"),
                    help="CA cert for TLS (default: relative to this script)")
    ap.add_argument("--target", required=True,
                    choices=["broadcast", "device", "group", "canary"])
    ap.add_argument("--version", default="3.1.0")
    ap.add_argument("--min-version", default="2.0.0")
    ap.add_argument("--url", default="")
    ap.add_argument("--sha256", default="")
    ap.add_argument("--id", default="", help="announce id (default: auto)")
    ap.add_argument("--device-id", default="", help="target device")
    ap.add_argument("--group", default="", help="target cohort group")
    ap.add_argument("--percent", type=int, default=40, help="canary percentage")
    args = ap.parse_args()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="lab-server-ota", protocol=mqtt.MQTTv311)
    client.username_pw_set(SERVER_USER, SERVER_PASS)
    if args.tls:
        client.tls_set(ca_certs=args.ca)
    client.connect(args.host, args.port, KEEPALIVE)
    client.loop_start()
    time.sleep(0.3)

    ann_id = args.id or ("ota-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    payload = make_announce(args, ann_id)

    try:
        if args.target == "broadcast":
            topic = OTA_ANNOUNCE
            client.publish(topic, json.dumps(payload), qos=1, retain=True)
            log("SERVER", c(f"broadcast (retained) -> {topic}: "
                            f"v{args.version} min {args.min_version} id {ann_id}",
                            "magenta"))
        elif args.target == "device":
            if not args.device_id:
                sys.exit("--device-id required for --target device")
            topic = ota_device_topic(args.device_id)
            client.publish(topic, json.dumps(payload), qos=1, retain=False)
            log("SERVER", c(f"targeted -> {topic}: v{args.version} id {ann_id}",
                            "magenta"))
        elif args.target == "group":
            if not args.group:
                sys.exit("--group required for --target group")
            topic = ota_group_topic(args.group)
            client.publish(topic, json.dumps(payload), qos=1, retain=False)
            log("SERVER", c(f"group -> {topic}: v{args.version} id {ann_id}",
                            "magenta"))
        elif args.target == "canary":
            groups = canary_groups_for_percent(args.percent)
            chosen_buckets = {int(g.split("-")[1]) for g in groups}
            chosen = {d for d in FLEET if canary_bucket(d) in chosen_buckets}
            for g in groups:
                topic = ota_group_topic(g)
                client.publish(topic, json.dumps(payload), qos=1, retain=False)
                log("SERVER", c(f"canary -> {topic}: v{args.version} id {ann_id}",
                                "magenta"))
            log("SERVER", f"canary {args.percent}% selects buckets {groups} -> "
                          f"actual coverage {len(chosen)}/{len(FLEET)} devices: "
                          f"{', '.join(sorted(chosen))}")
    finally:
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
