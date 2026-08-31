#!/usr/bin/env python3
"""Live MQTT traffic watcher for the agent-widget lab.

Connects as the fleet operator ('server') and pretty-prints every message on
the lab topics. Color-coded by namespace:
  agents/...  green   (AgentStatus)
  ota/...     magenta (OTA notifications)
  device/...  cyan    (device telemetry / events / results)

Examples:
  python3 tail.py
  python3 tail.py --filter esp32s3-778899
  python3 tail.py --tls
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt  # noqa: E402

from common import KEEPALIVE, SERVER_PASS, SERVER_USER, c, pretty  # noqa: E402


def _color_for(topic):
    if topic.startswith("agents/"):
        return "green"
    if topic.startswith("ota/"):
        return "magenta"
    if topic.startswith("device/"):
        return "cyan"
    return "grey"


def main():
    ap = argparse.ArgumentParser(description="MQTT lab traffic watcher")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--ca", default="../broker/certs/ca.crt")
    ap.add_argument("--filter", default="", help="only show topics containing this")
    args = ap.parse_args()

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"connect failed: {reason_code}")
            sys.exit(1)
        client.subscribe("#", qos=1)
        print(f">> watching # on {args.host}:{args.port}"
              f"{' (TLS)' if args.tls else ''} — Ctrl-C to stop\n")

    def on_message(client, userdata, msg):
        if args.filter and args.filter not in msg.topic:
            return
        color = _color_for(msg.topic)
        body = pretty(msg.payload)
        print(f"{c(msg.topic, color)} {'[retained]' if msg.retain else ''}\n"
              f"    {body}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="lab-tail", protocol=mqtt.MQTTv311)
    client.username_pw_set(SERVER_USER, SERVER_PASS)
    if args.tls:
        client.tls_set(ca_certs=args.ca)
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(args.host, args.port, KEEPALIVE)
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n>> stopped")


if __name__ == "__main__":
    main()
