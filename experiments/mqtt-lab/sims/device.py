#!/usr/bin/env python3
"""Virtual ESP32-S3 device for the agent-widget MQTT lab.

Simulates the future device behavior over MQTT:
  - persistent session (clean_session=False) + stable client_id == deviceId
  - QoS 1 subscriptions: agents/+/status, ota/announce, ota/{deviceId},
    ota/group/canary-{bucket}, ota/group/stable (+ --groups extras, which
    must be granted by the broker ACL)
  - per-device credential loaded from broker/state/device-creds.env
  - Last-Will offline telemetry (retained) so the fleet server sees drops;
    NOTE (MQTT 3.1.1): the will is fixed at connect time, so its `version`
    field reflects the version at (re)connect and may be stale after an OTA
    install — the retained online telemetry is always refreshed on install.
  - automatic reconnect with backoff via loop_forever (mirrors the ESP32
    MQTT task); no manual reconnect timers
  - OTA announce handling: version guard + min_version guard -> "download"
    (simulated) -> self-test -> install, or rollback when self-test fails.
    Announcements are processed by a single serial worker (no races on
    self.version), deduped by announce id.
  - failure injection: --offline-start (late joiner), --drop-every (graceful
    link cycle, does NOT fire LWT), --crash-after (hard process exit, DOES
    fire LWT), --fail-self-test (rollback drill)

Usage examples:
  python3 device.py --device-id esp32s3-a1b2c3
  python3 device.py --device-id esp32s3-778899 --fail-self-test
  python3 device.py --device-id esp32s3-112233 --offline-start 15
  python3 device.py --device-id esp32s3-445566 --crash-after 60
  python3 device.py --tls --ca broker/certs/ca.crt
"""

import argparse
import json
import os
import queue
import signal
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt  # noqa: E402

from common import (  # noqa: E402
    KEEPALIVE, OTA_ANNOUNCE, c, canary_group, events_topic, load_device_password,
    log, ota_device_topic, ota_group_topic, ota_result_topic, progress_bar,
    status_topic, telemetry_topic, version_cmp, build_event, build_ota_result,
    build_telemetry,
)

try:
    import jsonschema  # noqa: E402
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover
    _HAS_JSONSCHEMA = False


def _load_schema(name):
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "contracts", name)
    with open(p) as f:
        return json.load(f)


SCHEMAS = {
    "agent_status": _load_schema("agent-status-v1.schema.json"),
    "ota_announce": _load_schema("ota-announce-v1.schema.json"),
}

STATE_COLOR = {
    "IDLE": "blue", "RUNNING": "green", "BLOCKED": "yellow",
    "DONE": "cyan", "ERROR": "red", "OFFLINE": "grey",
}


class SimDevice:
    def __init__(self, args):
        self.args = args
        self.device_id = args.device_id
        self.version = args.version
        self.boot_ts = time.time()
        self.stopping = False
        self.fail_self_test = args.fail_self_test
        self.seen_announces = set()      # announce ids already processed
        self.agents = {}                 # agentId -> AgentStatus dict
        self._agent_last_seq = {}        # agentId -> last accepted seq
        self._was_connected = False
        self._ota_queue = queue.Queue()  # serial OTA worker (no version races)

        password = load_device_password(self.device_id, args.creds_file)
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.device_id,
            clean_session=False,        # persistent session: offline messages queue
            protocol=mqtt.MQTTv311,
        )
        self.client.username_pw_set(self.device_id, password)
        # MQTT 3.1.1: the will is fixed per connect; version is the
        # connect-time version and may be stale after an OTA install.
        self.client.will_set(
            telemetry_topic(self.device_id),
            payload=json.dumps(build_telemetry(self.device_id, False, self.version,
                                               "lwt", self._uptime())),
            qos=1, retain=True,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        # loop_forever() auto-reconnects with exponential backoff (like the
        # ESP32 MQTT task); no manual reconnect timers to race with it.
        self.client.reconnect_delay_set(min_delay=1, max_delay=8)

        if args.tls:
            self.client.tls_set(ca_certs=args.ca)

    # ------------------------------------------------------------------ core

    def start(self):
        log("DEVICE", c(f"{self.device_id} boot, fw {self.version} "
                        f"({'fail-self-test' if self.fail_self_test else 'healthy'})",
                        "bold"))
        if self.args.offline_start > 0:
            log("DEVICE", f"late join: connecting in {self.args.offline_start}s "
                          f"(proves retained broadcast delivery)")
            time.sleep(self.args.offline_start)
        self.client.connect(self.args.host, self.args.port, KEEPALIVE)
        # Run the network loop (with automatic reconnect + backoff) in its own
        # thread, mirroring a dedicated MQTT task on the ESP32.
        threading.Thread(target=self.client.loop_forever, daemon=True).start()
        # Serial OTA worker: announcements are processed one at a time.
        threading.Thread(target=self._ota_worker, daemon=True).start()

        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._panel_loop, daemon=True).start()
        if self.args.drop_every > 0:
            threading.Thread(target=self._wifi_drop_loop, daemon=True).start()
        if self.args.crash_after > 0:
            threading.Thread(target=self._crash_loop, daemon=True).start()

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
        self._alive = threading.Event()
        try:
            self._alive.wait()
        except KeyboardInterrupt:
            self._shutdown()

    def _shutdown(self, *_):
        if self.stopping:
            return
        self.stopping = True
        log("DEVICE", f"{self.device_id} graceful shutdown", "yellow")
        if self._was_connected:
            self._publish_telemetry("shutdown", online=False)
            self._publish_event("offline", {"cause": "shutdown"})
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:
            pass
        self._alive.set()

    # ------------------------------------------------------------ callbacks

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            if reason_code.value == 5:
                log("DEVICE", c(f"auth failed for {self.device_id} — provision "
                                "the device first: scripts/add-device-user.sh "
                                f"{self.device_id}", "red"))
            else:
                log("DEVICE", f"connect failed: {reason_code}", "red")
            self._alive.set()
            return
        self._was_connected = True
        subs = [
            ("agents/+/status", 1),
            (OTA_ANNOUNCE, 1),
            (ota_device_topic(self.device_id), 1),
            (ota_group_topic(canary_group(self.device_id)), 1),
            (ota_group_topic("stable"), 1),
        ] + [(ota_group_topic(g), 1) for g in self.args.groups]
        self.client.subscribe(subs)
        self._publish_telemetry("connect", online=True)
        self._publish_event("online", {"version": self.version})
        log("DEVICE", c(f"{self.device_id} connected (session resumed) — "
                        f"subscribed {len(subs)} topics", "green"))

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        if self.stopping:
            return
        # loop_forever() reconnects automatically; report the drop once.
        if self._was_connected:
            self._was_connected = False
            log("DEVICE", c(f"{self.device_id} disconnected ({reason_code})", "yellow"))
            self._publish_event("wifi_dropped", {"reason": str(reason_code)})

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            log("DEVICE", f"non-JSON payload on {msg.topic}, ignoring", "red")
            return

        if msg.topic.startswith("agents/"):
            self._on_agent_status(msg.topic, payload)
        elif msg.topic.startswith("ota/"):
            self._on_ota(msg.topic, payload)

    # ------------------------------------------------------------ status UI

    def _on_agent_status(self, topic, payload):
        if not self._validate("agent_status", payload, topic):
            return
        agent_id = topic.split("/")[1]
        # Topic/payload identity agreement + monotonic sequence guard: reject
        # stale or replayed statuses (per-agent).
        if payload.get("agentId") != agent_id:
            log("DEVICE", f"agentId mismatch: topic says {agent_id}, payload says "
                          f"{payload.get('agentId')} — ignoring", "red")
            return
        last = self._agent_last_seq.get(agent_id, -1)
        if payload.get("seq", 0) <= last:
            log("DEVICE", f"stale status for {agent_id} (seq {payload.get('seq')} "
                          f"<= {last}) — ignoring", "yellow")
            return
        self._agent_last_seq[agent_id] = payload.get("seq", 0)

        self.agents[agent_id] = payload
        st = payload.get("state", "?")
        pct = payload.get("progress")
        line = (f"{c(agent_id, STATE_COLOR.get(st, 'grey'))} "
                f"{c(st, STATE_COLOR.get(st, 'grey'))} seq={payload.get('seq')}")
        if pct is not None:
            line += f" {progress_bar(pct)} {pct}%"
        if payload.get("activity"):
            line += f"  {payload.get('activity')}"
        log("DEVICE", f"▸ {line}")
        self._publish_event("status_rendered", {"agentId": agent_id, "state": st})

    # --------------------------------------------------------------- OTA

    def _on_ota(self, topic, payload):
        if not self._validate("ota_announce", payload, topic):
            return
        ann_id = payload["id"]
        if ann_id in self.seen_announces:
            return  # dedupe (e.g. retained broadcast re-delivered on reconnect)
        self.seen_announces.add(ann_id)
        self._ota_queue.put((topic, payload))

    def _ota_worker(self):
        while not self.stopping:
            topic, payload = self._ota_queue.get()
            try:
                self._process_ota(topic, payload)
            except Exception as e:
                log("DEVICE", f"OTA processing error: {e}", "red")

    def _process_ota(self, topic, payload):
        new_v, min_v, ann_id = payload["version"], payload["min_version"], payload["id"]
        cur = self.version
        log("DEVICE", c(f"OTA announce on {topic}: {cur} -> {new_v} "
                        f"(min {min_v}, id {ann_id})", "magenta"))

        if version_cmp(new_v, cur) == 0:
            self._reject(ann_id, cur, new_v, "rejected_same", "already on this version")
            return
        if version_cmp(new_v, cur) < 0:
            self._reject(ann_id, cur, new_v, "rejected_older",
                         "anti-downgrade guard (recall protection)")
            return
        if version_cmp(cur, min_v) < 0:
            self._reject(ann_id, cur, new_v, "rejected_min_version",
                         f"current {cur} < min_version {min_v}")
            return

        self._publish_result(ann_id, cur, new_v, "accepted")
        self._publish_event("ota_accepted", {"announceId": ann_id, "from": cur,
                                             "to": new_v})
        log("DEVICE", c(f"update available {cur} -> {new_v}, downloading "
                        f"({payload['url']})", "bold"))

        # Simulated HTTPS download + sha256/RSA verification (metadata is only
        # a trigger; integrity is enforced on the binary, exactly like prod).
        time.sleep(2.0 * self.args.fast_scale)
        if self.args.check_url:
            self._head_check(payload["url"])

        if self.fail_self_test:
            log("DEVICE", c("self-test FAILED (display/transport) -> rolling back "
                            "to previous slot", "red"))
            self._publish_result(ann_id, cur, new_v, "rolled_back")
            self._publish_event("ota_rolled_back",
                                {"announceId": ann_id, "from": cur, "to": new_v,
                                 "reason": "self_test_failed"})
            return

        old = self.version
        self.version = new_v
        self._publish_telemetry("install", online=True)
        self._publish_result(ann_id, cur, new_v, "installed")
        self._publish_event("ota_installed", {"announceId": ann_id, "from": cur,
                                              "to": new_v})
        self._publish_event("version_changed", {"from": old, "to": new_v})
        log("DEVICE", c(f"installed {old} -> {new_v} on inactive slot, reboot OK, "
                        "self-test passed", "green"))

    def _reject(self, ann_id, cur, new_v, outcome, reason):
        self._publish_result(ann_id, cur, new_v, outcome)
        self._publish_event("ota_rejected", {"announceId": ann_id, "from": cur,
                                             "to": new_v, "reason": reason})
        log("DEVICE", c(f"rejected {new_v}: {reason}", "yellow"))

    def _head_check(self, url):
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=5) as r:
                log("DEVICE", f"HTTPS download check: {r.status} "
                              f"{len(r.headers.get('Content-Length', ''))} bytes")
        except Exception as e:
            log("DEVICE", f"HTTPS download check failed (warn only): {e}", "yellow")

    # ------------------------------------------------------------- publish

    def _publish_telemetry(self, cause, online=True):
        payload = build_telemetry(self.device_id, online, self.version, cause,
                                  self._uptime())
        self.client.publish(telemetry_topic(self.device_id),
                            json.dumps(payload), qos=1, retain=True)

    def _publish_event(self, evt, detail=None):
        if self.args.events and self._was_connected:
            self.client.publish(events_topic(self.device_id),
                                json.dumps(build_event(self.device_id, evt, detail)),
                                qos=1, retain=False)

    def _publish_result(self, ann_id, from_v, to_v, outcome):
        payload = build_ota_result(self.device_id, ann_id, from_v, to_v, outcome)
        self.client.publish(ota_result_topic(self.device_id),
                            json.dumps(payload), qos=1, retain=True)

    # -------------------------------------------------------------- loops

    def _heartbeat_loop(self):
        while not self.stopping:
            time.sleep(10)
            if self._was_connected:
                self._publish_telemetry("heartbeat", online=True)

    def _panel_loop(self):
        """Periodic snapshot of the device screen (the simulated Panel UI)."""
        while not self.stopping:
            time.sleep(15)
            if not self.agents:
                continue
            log("DEVICE", c(f"--- screen: {self.device_id} (fw {self.version}) ---",
                            "bold"))
            for agent_id, st in sorted(self.agents.items()):
                color = STATE_COLOR.get(st.get("state"), "grey")
                pct = st.get("progress")
                bar = f"{progress_bar(pct)} {pct}%" if pct is not None else " " * 20
                print(f"    {c(agent_id, 'bold')} {c(st.get('state','?'), color)} "
                      f"{bar}  {st.get('activity','')}", flush=True)
            print(flush=True)

    def _wifi_drop_loop(self):
        """Graceful link cycle (disconnect + reconnect after a pause).

        client.disconnect() is a graceful MQTT DISCONNECT: it does NOT fire
        the Last Will. For an ungraceful drop that fires LWT use
        --crash-after or the demo's SIGSTOP drill instead.
        """
        n = 0
        while not self.stopping:
            n += 1
            time.sleep(self.args.drop_every)
            if self.stopping or not self._was_connected:
                continue
            log("DEVICE", c(f"wifi drop #{n}: graceful link cycle for "
                            f"{self.args.drop_duration}s (no LWT — graceful "
                            "DISCONNECT)", "yellow"))
            try:
                self.client.disconnect()
            except Exception:
                pass
            time.sleep(self.args.drop_duration)
            # loop_forever() reconnects automatically

    def _crash_loop(self):
        """Hard-kill the process after N seconds to fire the real LWT."""
        time.sleep(self.args.crash_after)
        log("DEVICE", c(f"simulated crash after {self.args.crash_after}s — "
                        "process exits, broker fires LWT offline", "red"))
        os._exit(1)

    # -------------------------------------------------------------- utils

    def _validate(self, kind, payload, topic):
        if not _HAS_JSONSCHEMA:
            return True
        try:
            jsonschema.validate(payload, SCHEMAS[kind])
            return True
        except jsonschema.ValidationError as e:
            log("DEVICE", f"schema violation on {topic}: {e.message}", "red")
            return False

    def _uptime(self):
        return int(time.time() - self.boot_ts)


def main():
    ap = argparse.ArgumentParser(description="Virtual ESP32-S3 device (MQTT lab)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true", help="connect to 8883 with TLS")
    ap.add_argument("--ca",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "broker", "certs", "ca.crt"),
                    help="CA cert for TLS (default: relative to this script)")
    ap.add_argument("--creds-file",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "broker", "state",
                                         "device-creds.env"),
                    help="per-device credential file (default: relative to script)")
    ap.add_argument("--device-id", required=True)
    ap.add_argument("--version", default="2.0.0", help="starting firmware version")
    ap.add_argument("--offline-start", type=float, default=0,
                    help="delay connect (late joiner test)")
    ap.add_argument("--drop-every", type=float, default=0,
                    help="graceful link cycle every N seconds (0=off; no LWT)")
    ap.add_argument("--drop-duration", type=float, default=4)
    ap.add_argument("--crash-after", type=float, default=0,
                    help="hard-exit after N seconds to fire the real LWT (0=off)")
    ap.add_argument("--groups", default="",
                    help="extra cohort groups to subscribe to (comma-separated; "
                         "must be granted in the broker ACL)")
    ap.add_argument("--fail-self-test", action="store_true",
                    help="rollback drill: always fail the post-OTA self-test")
    ap.add_argument("--check-url", action="store_true",
                    help="HEAD-check the announce URL during 'download'")
    ap.add_argument("--events", action=argparse.BooleanOptionalAction, default=True,
                    help="publish lifecycle events to device/{id}/events")
    ap.add_argument("--fast", action="store_true", help="shrink simulated delays")
    args = ap.parse_args()
    args.fast_scale = 0.3 if args.fast else 1.0
    args.groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    SimDevice(args).start()


if __name__ == "__main__":
    main()
