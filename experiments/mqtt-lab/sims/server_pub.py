#!/usr/bin/env python3
"""Server-side AgentStatus publisher for the agent-widget MQTT lab.

Simulates the future fleet server: publishes versioned AgentStatus v1 JSON
(state codes only, language-independent) to agents/{agentId}/status with
QoS 1 + retained, so any device that connects later still sees the current
state of every agent.

Examples:
  python3 server_pub.py --once --agents claude-01,deepseek-02
  python3 server_pub.py --loop --interval 5 --steps 40 --agents claude-01,deepseek-02,codex-03
  python3 server_pub.py --once --agents codex-03 --state BLOCKED --progress 61
"""

import argparse
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt  # noqa: E402

from common import (  # noqa: E402
    DEFAULT_AGENTS, SERVER_PASS, SERVER_USER, KEEPALIVE, build_agent_status,
    log, status_topic, c,
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


SCHEMA = _load_schema("agent-status-v1.schema.json")

# state-machine walk: state -> possible next states
_TRANSITIONS = {
    "IDLE": ["RUNNING"],
    "RUNNING": ["RUNNING", "BLOCKED", "DONE", "ERROR"],
    "BLOCKED": ["RUNNING", "DONE"],
    "DONE": ["IDLE"],
    "ERROR": ["IDLE"],
}
_MODELS = {"claude-01": "claude-4", "deepseek-02": "deepseek-v4-pro",
           "codex-03": "codex-2"}


class AgentWalker:
    def __init__(self, agent_id, seed_state=None):
        self.agent_id = agent_id
        self.state = seed_state or "IDLE"
        self.seq = 0
        self.progress = 0
        self.activity = ""

    def step(self):
        self.seq += 1
        self.state = random.choice(_TRANSITIONS[self.state])
        if self.state == "RUNNING":
            self.progress = min(99, self.progress + random.randint(1, 25))
            self.activity = random.choice([
                "running brief: AW-004 mqtt",
                "editing sims/device.py",
                "reviewing schema v1",
                "verifying broker TLS",
            ])
        elif self.state == "BLOCKED":
            self.activity = random.choice(["waiting for approval", "awaiting user input"])
        elif self.state in ("DONE", "IDLE"):
            self.progress = 100 if self.state == "DONE" else 0
            self.activity = "task complete" if self.state == "DONE" else "idle"
        elif self.state == "ERROR":
            self.activity = "tool call failed"
        return build_agent_status(self.agent_id, self.state, self.seq,
                                  activity=self.activity,
                                  progress=self.progress if self.state
                                  in ("RUNNING", "BLOCKED") else None,
                                  model=_MODELS.get(self.agent_id, ""),
                                  task=f"aw-{random.randint(1, 20):03d}")


def publish_once(client, agents, forced_state=None):
    for aid in agents:
        w = AgentWalker(aid)
        if forced_state:
            w.state = forced_state
            w.activity = {"BLOCKED": "waiting for approval", "ERROR": "tool call failed",
                          "DONE": "task complete", "IDLE": "idle"}.get(forced_state, "")
            w.progress = {"BLOCKED": 61, "RUNNING": 42, "DONE": 100}.get(forced_state, 0)
        payload = w.step()
        if _HAS_JSONSCHEMA:
            jsonschema.validate(payload, SCHEMA)
        client.publish(status_topic(aid), json.dumps(payload), qos=1, retain=True)
        st = payload["state"]
        line = (f"{c(aid, 'bold')} {c(st, {'IDLE': 'blue', 'RUNNING': 'green',
                                            'BLOCKED': 'yellow', 'DONE': 'cyan',
                                            'ERROR': 'red'}.get(st, 'grey'))} "
                f"seq={payload['seq']}")
        if payload.get("progress") is not None:
            line += f" {payload['progress']}%"
        log("SERVER", f"published retained -> agents/{aid}/status: {line}")


def main():
    ap = argparse.ArgumentParser(description="AgentStatus publisher (MQTT lab)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--ca",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "broker", "certs", "ca.crt"),
                    help="CA cert for TLS (default: relative to this script)")
    ap.add_argument("--agents", default=",".join(DEFAULT_AGENTS),
                    help="comma-separated agent ids")
    ap.add_argument("--state", choices=["IDLE", "RUNNING", "BLOCKED", "DONE",
                                        "ERROR", "OFFLINE"])
    ap.add_argument("--once", action="store_true", help="publish one snapshot and exit")
    ap.add_argument("--loop", action="store_true", help="publish continuously")
    ap.add_argument("--interval", type=float, default=5)
    ap.add_argument("--steps", type=int, default=0, help="0 = run forever")
    args = ap.parse_args()
    agents = [a.strip() for a in args.agents.split(",") if a.strip()]

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="lab-server-pub", protocol=mqtt.MQTTv311)
    client.username_pw_set(SERVER_USER, SERVER_PASS)
    if args.tls:
        client.tls_set(ca_certs=args.ca)
    client.connect(args.host, args.port, KEEPALIVE)
    client.loop_start()
    time.sleep(0.3)

    try:
        if args.once or not args.loop:
            publish_once(client, agents, args.state)
            return
        n = 0
        while not args.steps or n < args.steps:
            publish_once(client, agents, args.state)
            n += 1
            time.sleep(args.interval)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
