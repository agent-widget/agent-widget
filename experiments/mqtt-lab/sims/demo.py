#!/usr/bin/env python3
"""End-to-end scenario for the agent-widget MQTT lab (self-verifying).

Proves the future production behaviors on a local broker:

  1. fleet of virtual devices boots, reports online (telemetry + LWT)
  2. AgentStatus v1 statuses are delivered and rendered (retained)
  3. OTA canary rollout: hash(deviceId) buckets -> only the chosen % installs
  4. OTA group rollout (stable) -> the rest of the fleet
  5. offline device + persistent session: targeted announce is queued and
     delivered on reconnect (SIGSTOP/SIGCONT injection)
  6. retained broadcast: a device that joins late still installs the
     announced version and renders the retained statuses
  7. recall guard: an older announce is rejected by EVERY device
     (anti-downgrade) and a min_version wall rejects upgrades by EVERY device
     (anti-rollback floor)
  8. rollback drill: a device with failing self-test rolls back and keeps
     its previous firmware version
  9. ACL negative probes: a device credential cannot write another device's
     telemetry, nor subscribe to another device's targeted/cohort topics

Run:  python3 demo.py            (broker must be running, see scripts/start-broker.sh)
      python3 demo.py --fast     (shorter simulated delays)
Exit code 0 == every check passed.
"""

import argparse
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paho.mqtt.client as mqtt  # noqa: E402

from common import (  # noqa: E402
    DEFAULT_AGENTS, FLEET, KEEPALIVE, SERVER_PASS, SERVER_USER, canary_bucket,
    canary_groups_for_percent, c, load_device_password, ota_group_topic,
    status_topic, telemetry_topic, ota_result_topic, build_agent_status,
    build_ota_announce, default_ota_url,
)

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(os.path.dirname(HERE), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

ROLE = {
    "esp32s3-a1b2c3": "normal",
    "esp32s3-d4e5f6": "normal",
    "esp32s3-778899": "rollback-drill (fail self-test)",
    "esp32s3-112233": "offline-queue target",
    "esp32s3-445566": "late joiner (offline-start 45s)",
}
ROLLBACK_DEV = "esp32s3-778899"
LATE_DEV = "esp32s3-445566"
OFFLINE_DEV = "esp32s3-112233"
PROBE_DEV = "esp32s3-a1b2c3"
PROBE_OTHER = "esp32s3-d4e5f6"

CANARY_ANN = "ota-demo-canary"
STABLE_ANN = "ota-demo-stable"
TARGETED_ANN = "ota-demo-targeted"
BROADCAST_ANN = "ota-demo-broadcast"
RECALL_ANN = "ota-demo-recall"
MINWALL_ANN = "ota-demo-minwall"


class Collector:
    """Fleet-operator client that records everything the devices report."""

    def __init__(self, host, port, tls, ca):
        self.host, self.port, self.tls, self.ca = host, port, tls, ca
        self.statuses = {}          # agentId -> payload (retained on subscribe)
        self.telemetry = {}         # deviceId -> last telemetry
        self.events = []            # (deviceId, evt, detail, ts)
        self.ota_results = {}       # deviceId -> last ota result
        self.ready = threading.Event()
        self.sub_acked = threading.Event()

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="lab-demo-collector",
                                  protocol=mqtt.MQTTv311)
        self.client.username_pw_set(SERVER_USER, SERVER_PASS)
        if tls:
            self.client.tls_set(ca_certs=ca)
        self.client.on_connect = self._on_connect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.connect(host, port, KEEPALIVE)
        self.client.loop_start()
        assert self.ready.wait(5), "collector could not connect to the broker"
        assert self.sub_acked.wait(5), "collector subscriptions were not acked"

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"collector connect failed: {reason_code}")
            sys.exit(1)
        self.client.subscribe([(f"agents/+/status", 1),
                               (f"device/+/telemetry", 1),
                               (f"device/+/events", 1),
                               (f"device/+/ota/result", 1)])
        self.ready.set()

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        self.sub_acked.set()

    def _on_message(self, client, userdata, msg):
        t = msg.topic
        if not msg.payload:
            # empty retained payload = retained message cleared
            if t.startswith("agents/"):
                self.statuses.pop(t.split("/")[1], None)
            elif "/telemetry" in t:
                self.telemetry.pop(t.split("/")[1], None)
            elif "/ota/result" in t:
                self.ota_results.pop(t.split("/")[1], None)
            return
        try:
            p = json.loads(msg.payload)
        except Exception:
            return
        if not isinstance(p, dict):
            return
        if t.startswith("agents/"):
            self.statuses[t.split("/")[1]] = p
        elif "/telemetry" in t:
            self.telemetry[p["deviceId"]] = p
        elif "/ota/result" in t:
            self.ota_results[p["deviceId"]] = p
        elif "/events" in t:
            self.events.append((p["deviceId"], p["evt"], p.get("detail"), p["ts"]))

    # ------------------------------------------------------------- queries

    def events_of(self, device_id, evt=None):
        out = [e for e in self.events if e[0] == device_id]
        if evt:
            out = [e for e in out if e[1] == evt]
        return out

    def has_event(self, device_id, evt, announce_id=None):
        for e in self.events_of(device_id, evt):
            if announce_id is None or (e[2] or {}).get("announceId") == announce_id:
                return True
        return False

    def version_of(self, device_id):
        t = self.telemetry.get(device_id)
        return t["version"] if t else None

    def online_of(self, device_id):
        t = self.telemetry.get(device_id)
        return bool(t and t.get("online"))

    def wait_until(self, desc, pred, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if pred():
                return True
            time.sleep(0.5)
        print(f"    {c('✗ timeout', 'red')} waiting for: {desc}")
        return False


class Demo:
    def __init__(self, args, broker_ok):
        self.args = args
        self.host, self.port = args.host, args.port
        self.fast = args.fast
        self.broker_ok = broker_ok
        self.checks = []           # (name, ok)
        self.failures = []
        self.procs = {}
        self.device_py = os.path.join(HERE, "device.py")

    # ------------------------------------------------------------- helpers

    def check(self, name, ok, detail=""):
        self.checks.append((name, bool(ok)))
        mark = c("✓", "green") if ok else c("✗", "red")
        print(f"  {mark} {name}" + (f"  {c(detail, 'grey')}" if detail else ""))

    def section(self, title):
        print(f"\n{c('=== ' + title + ' ===', 'bold')}")

    def spawn_device(self, device_id, *extra):
        cmd = [sys.executable, self.device_py, "--host", self.host,
               "--port", str(self.port), "--device-id", device_id]
        if self.fast:
            cmd.append("--fast")
        cmd += list(extra)
        logf = open(os.path.join(LOG_DIR, f"{device_id}.log"), "w")
        p = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, text=True)
        self.procs[device_id] = (p, logf)

    def publish(self, payload, topic, qos=1, retain=False):
        # payload=None -> zero-length MQTT payload (used to CLEAR retained
        # messages per spec). Anything else is JSON-encoded.
        wire = None if payload is None else json.dumps(payload)
        info = self.collector.client.publish(topic, wire, qos=qos, retain=retain)
        info.wait_for_publish(5)

    def stop_device(self, device_id):
        p, logf = self.procs[device_id]
        p.send_signal(signal.SIGTERM)
        p.wait(timeout=10)
        logf.close()

    def wait_fleet_online(self, devices, timeout):
        return self.collector.wait_until(
            f"all {len(devices)} devices report online",
            lambda: all(self.collector.online_of(d) for d in devices), timeout)

    def _announce(self, version, min_version, ann_id):
        return build_ota_announce(
            version=version,
            url=default_ota_url(version),
            sha256=hashlib.sha256(f"firmware-{version}".encode()).hexdigest(),
            signature="TUFHLVJBQ0lOR1RFTkRVTVNJR05BVFVSRUxBQk9OTFk=",
            min_version=min_version,
            ann_id=ann_id,
        )

    def _t(self, seconds):
        return max(3, int(seconds * (0.4 if self.fast else 1.0)))

    # ------------------------------------------------------------ scenario

    def clear_retained(self):
        """Wipe the lab-owned retained topics from previous runs.

        Bounded to the topics this lab owns (default agents + fleet + the
        broadcast topic), NOT "every retained message on the broker".
        Runs only after the collector's subscriptions are acked.
        """
        cleared = []
        for aid in DEFAULT_AGENTS:
            self.publish(None, status_topic(aid), qos=1, retain=True)
            cleared.append(status_topic(aid))
        self.publish(None, "ota/announce", qos=1, retain=True)
        cleared.append("ota/announce")
        for dev in FLEET:
            self.publish(None, telemetry_topic(dev), qos=1, retain=True)
            self.publish(None, ota_result_topic(dev), qos=1, retain=True)
            cleared.append(telemetry_topic(dev))
        self.collector.wait_until(
            "lab retained topics cleared",
            lambda: not any(dev in self.collector.telemetry for dev in FLEET)
            and not self.collector.statuses
            and not any(dev in self.collector.ota_results for dev in FLEET), 5)
        print(f"    cleared {len(cleared)} lab-owned retained topics")

    # ----------------------------------------------------- ACL probes (B5)

    def _acl_probe(self, label, act, timeout=6):
        """Negative probe: a device credential must NOT be able to `act`.

        Returns True if the broker refused the operation (connection dropped
        or the operation returned a failure code), False otherwise.
        """
        result = {"disconnected": False, "denied": False}

        def on_disconnect(client, userdata, flags, rc, props):
            result["disconnected"] = True

        def on_subscribe(client, userdata, mid, reason_codes, props):
            for rc in reason_codes:
                if getattr(rc, "is_failure", False):
                    result["denied"] = True

        def on_publish(client, userdata, mid, reason_code, props):
            if getattr(reason_code, "is_failure", False):
                result["denied"] = True

        probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                            client_id=f"lab-acl-probe-{abs(hash(label))}",
                            clean_session=True, protocol=mqtt.MQTTv311)
        probe.username_pw_set(PROBE_DEV,
                              load_device_password(PROBE_DEV))
        probe.on_disconnect = on_disconnect
        probe.on_subscribe = on_subscribe
        probe.on_publish = on_publish
        probe.connect(self.host, self.port, KEEPALIVE)
        probe.loop_start()
        time.sleep(0.5)
        act(probe)
        deadline = time.time() + timeout
        while time.time() < deadline and not (result["disconnected"] or result["denied"]):
            time.sleep(0.2)
        probe.loop_stop()
        try:
            probe.disconnect()
        except Exception:
            pass
        ok = result["disconnected"] or result["denied"]
        self.check(f"ACL denies: {label}", ok,
                   "dropped" if result["disconnected"] else
                   "operation failed" if result["denied"] else "NOT refused!")
        return ok

    def acl_negative_probes(self):
        self.section("9. ACL negative probes (device credential isolation)")
        self._acl_probe(
            "device cannot write another device's telemetry",
            lambda c: c.publish(f"device/{PROBE_OTHER}/telemetry",
                                json.dumps({"hack": True}), qos=1))
        self._acl_probe(
            "device cannot subscribe to another device's targeted OTA topic",
            lambda c: c.subscribe(f"ota/{PROBE_OTHER}", qos=1))
        self._acl_probe(
            "device cannot subscribe to an unauthorized cohort group (beta)",
            lambda c: c.subscribe(ota_group_topic("beta"), qos=1))
        self._acl_probe(
            "device cannot subscribe to another device's telemetry",
            lambda c: c.subscribe(f"device/{PROBE_OTHER}/#", qos=1))
        self._takeover_probe()

    def _takeover_probe(self):
        """Client-ID takeover: mosquitto does NOT bind client_id to the
        authenticated user, so a credential that knows another device's id can
        evict that device's connection. This probe documents the CURRENT lab
        behavior (takeover succeeds); production must bind identity to
        client ID (mutual TLS or an auth plugin) — see README limitations.
        """
        before = len(self.collector.events_of(PROBE_OTHER))
        result = {"connected": None}

        def on_connect(client, userdata, flags, rc, props):
            result["connected"] = not rc.is_failure

        takeover = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                               client_id=PROBE_OTHER,  # another device's id!
                               clean_session=True, protocol=mqtt.MQTTv311)
        takeover.username_pw_set(PROBE_DEV, load_device_password(PROBE_DEV))
        takeover.on_connect = on_connect
        takeover.connect(self.host, self.port, KEEPALIVE)
        takeover.loop_start()
        time.sleep(0.5)
        ok_connect = result["connected"] is True
        # The evicted device (PROBE_OTHER) should drop and auto-reconnect.
        evicted = self.collector.wait_until(
            f"{PROBE_OTHER} dropped and reconnected after takeover",
            lambda: any(e[1] == "wifi_dropped" for e in
                        self.collector.events_of(PROBE_OTHER)[before:]), 15)
        takeover.loop_stop()
        try:
            takeover.disconnect()
        except Exception:
            pass
        self.check(
            "client-ID takeover possible without auth binding (documented lab "
            "limitation; production must bind client_id)",
            ok_connect and evicted,
            f"takeover connect={ok_connect}, victim reconnected={evicted}")

    # ------------------------------------------------------------- main run

    def run(self):
        self.collector = Collector(self.host, self.port, self.args.tls, self.args.ca)

        self.section("0. broker reachability (plaintext + optional TLS)")
        self.check("broker reachable on %s:%s" % (self.host, self.port),
                   self.broker_ok and self.collector.ready.is_set())
        if self.args.tls:
            # collector connected over TLS or it would not have been built
            self.check("TLS transport established (collector connected)", True)
        self.clear_retained()

        self.section("1. fleet boots (telemetry + LWT)")
        for dev, role in ROLE.items():
            extra = []
            if dev == ROLLBACK_DEV:
                extra = ["--fail-self-test"]
            if dev == LATE_DEV:
                extra = ["--offline-start", "45"]
            self.spawn_device(dev, *extra)
            print(f"    spawned {dev} ({role})")

        online_ok = self.wait_fleet_online([d for d in ROLE if d != LATE_DEV], 25)
        self.check("fleet d1-d4 online (retained telemetry)", online_ok)

        self.section("2. AgentStatus v1 delivery (retained, language-independent)")
        for aid in DEFAULT_AGENTS:
            self.publish(build_agent_status(aid, "RUNNING", seq=1,
                                            activity=f"executing {aid}",
                                            progress=42, model="claude-4",
                                            task="aw-004"),
                         status_topic(aid), qos=1, retain=True)
        got_statuses = self.collector.wait_until(
            "all 3 statuses retained on broker",
            lambda: len(self.collector.statuses) >= len(DEFAULT_AGENTS)
            and all(a in self.collector.statuses for a in DEFAULT_AGENTS), 5)
        self.check("3 AgentStatus v1 retained on agents/+/status", got_statuses)

        self.section("3. OTA canary rollout (hash buckets, 40%)")
        canary_groups = canary_groups_for_percent(40)
        canary_buckets = {int(g.split("-")[1]) for g in canary_groups}
        canary_devs = {d for d in FLEET if canary_bucket(d) in canary_buckets}
        canary_online = [d for d in canary_devs
                         if d not in (ROLLBACK_DEV, LATE_DEV)]
        print(f"    buckets {sorted(canary_buckets)} -> devices: "
              f"{', '.join(sorted(canary_devs))} "
              f"(asserting on {len(canary_online)} online candidates)")
        for g in canary_groups:
            self.publish(self._announce("3.1.0", "2.0.0", CANARY_ANN),
                         ota_group_topic(g), qos=1, retain=False)
        canary_ok = self.collector.wait_until(
            "canary devices install 3.1.0 (with the canary announce id)",
            lambda: bool(canary_online) and all(
                self.collector.version_of(d) == "3.1.0"
                and self.collector.has_event(d, "ota_installed", CANARY_ANN)
                for d in canary_online), self._t(12))
        self.check("canary devices upgraded to 3.1.0 (event-verified)", canary_ok)
        # non-canary devices must not have accepted THIS announce
        non_canary = [d for d in FLEET if d not in canary_devs]
        no_leak = all(
            not self.collector.has_event(d, "ota_accepted", CANARY_ANN)
            for d in non_canary)
        self.check("non-canary devices untouched (no canary leak)", no_leak)

        self.section("4. OTA group rollout (stable cohort)")
        self.publish(self._announce("3.1.0", "2.0.0", STABLE_ANN),
                     "ota/group/stable", qos=1, retain=False)
        # The late joiner is offline by design and only ever receives the
        # retained broadcast (step 6), never non-retained groups.
        stable_targets = [d for d in FLEET if d not in canary_devs
                          and d != LATE_DEV]
        stable_ok = self.collector.wait_until(
            "stable cohort upgrades to 3.1.0 (with the stable announce id)",
            lambda: bool(stable_targets) and all(
                self.collector.version_of(d) == "3.1.0"
                and self.collector.has_event(d, "ota_installed", STABLE_ANN)
                for d in stable_targets if ROLE[d] != "rollback-drill (fail self-test)"),
            self._t(12))
        self.check("stable cohort upgraded to 3.1.0 (event-verified)", stable_ok)
        rollback_ok = self.collector.wait_until(
            "rollback-drill device rolled back",
            lambda: self.collector.has_event(ROLLBACK_DEV, "ota_rolled_back"),
            self._t(12))
        self.check("fail-self-test device rolled back, keeps fw "
                   f"{self.collector.version_of(ROLLBACK_DEV)}", rollback_ok)

        self.section("5. offline device + persistent session (queued announce)")
        p, _ = self.procs[OFFLINE_DEV]
        print(f"    SIGSTOP {OFFLINE_DEV} (freeze the process; broker will see LWT offline)")
        p.send_signal(signal.SIGSTOP)
        # The frozen device cannot publish anything itself: the offline signal
        # is the broker-side retained LWT telemetry replacing online=true.
        lwt_ok = self.collector.wait_until(
            f"{OFFLINE_DEV} reported offline via broker LWT",
            lambda: (lambda t: t and not t.get("online") and t.get("cause") == "lwt")(
                self.collector.telemetry.get(OFFLINE_DEV)), 40)
        self.check("broker detected the drop and fired LWT offline", lwt_ok)

        self.publish(self._announce("3.2.0", "2.0.0", TARGETED_ANN),
                     f"ota/{OFFLINE_DEV}", qos=1, retain=False)
        print(f"    targeted 3.2.0 published while {OFFLINE_DEV} is offline (queued)")
        time.sleep(1)
        p.send_signal(signal.SIGCONT)
        print(f"    SIGCONT {OFFLINE_DEV} -> reconnects, persistent session delivers the queue")
        queued_ok = self.collector.wait_until(
            f"{OFFLINE_DEV} installs the queued 3.2.0",
            lambda: self.collector.version_of(OFFLINE_DEV) == "3.2.0"
            and self.collector.has_event(OFFLINE_DEV, "ota_installed", TARGETED_ANN), 30)
        self.check("queued announce delivered on reconnect, installed 3.2.0 "
                   "(event-verified)", queued_ok)
        others_untouched = all(self.collector.version_of(d) != "3.2.0"
                               for d in FLEET if d != OFFLINE_DEV)
        self.check("no other device saw the targeted announce (ACL isolation)",
                   others_untouched)

        self.section("6. retained broadcast + late joiner")
        expected_bc = [d for d in FLEET if d not in (ROLLBACK_DEV, LATE_DEV)]
        self.publish(self._announce("3.3.0", "2.0.0", BROADCAST_ANN),
                     "ota/announce", qos=1, retain=True)
        bc_ok = self.collector.wait_until(
            "explicit online set installs 3.3.0 (event-verified)",
            lambda: all(
                self.collector.version_of(d) == "3.3.0"
                and self.collector.has_event(d, "ota_installed", BROADCAST_ANN)
                for d in expected_bc), self._t(14))
        self.check("broadcast upgrade to 3.3.0 (explicit set, event-verified)",
                   bc_ok, f"expected {expected_bc}")

        late_ok = self.collector.wait_until(
            f"late joiner {LATE_DEV} connects and installs retained 3.3.0",
            lambda: self.collector.version_of(LATE_DEV) == "3.3.0"
            and self.collector.has_event(LATE_DEV, "ota_installed", BROADCAST_ANN), 45)
        self.check("late joiner received retained broadcast and installed "
                   "(event-verified)", late_ok)
        rendered_ok = self.collector.wait_until(
            "late joiner renders the retained AgentStatuses",
            lambda: len(self.collector.events_of(LATE_DEV, "status_rendered")) >= 3, 15)
        rendered = len(self.collector.events_of(LATE_DEV, "status_rendered"))
        self.check("late joiner rendered retained AgentStatuses (>=3)",
                   rendered_ok, f"({rendered} rendered)")
        leaked_events = [e for e in self.collector.events_of(LATE_DEV)
                         if e[1] == "ota_accepted"
                         and (e[2] or {}).get("announceId") in (CANARY_ANN,
                                                                 TARGETED_ANN)]
        self.check("late joiner never received canary or other-device-targeted "
                   "announces (its own cohort groups may queue legitimately)",
                   not leaked_events)

        self.section("7. recall guards (anti-downgrade + min_version wall)")
        # Every device is online now (the late joiner joined at step 6).
        all_online = list(FLEET)
        self.publish(self._announce("3.0.0", "3.3.0", RECALL_ANN),
                     "ota/announce", qos=1, retain=True)
        recall_ok = self.collector.wait_until(
            "EVERY device rejects the older recall announce",
            lambda: all(self.collector.has_event(d, "ota_rejected", RECALL_ANN)
                        for d in all_online), 12)
        self.check("older announce rejected by every device "
                   "(anti-downgrade recall guard)", recall_ok)

        self.publish(self._announce("3.4.0", "9.9.9", MINWALL_ANN),
                     "ota/announce", qos=1, retain=True)
        wall_ok = self.collector.wait_until(
            "EVERY device rejects the min_version wall announce",
            lambda: all(self.collector.has_event(d, "ota_rejected", MINWALL_ANN)
                        for d in all_online), 12)
        self.check("upgrade above min_version wall rejected by every device",
                   wall_ok)

        self.acl_negative_probes()

        self.section("8. summary")
        self._summary()

    # ------------------------------------------------------------ summary

    def _summary(self):
        rows = []
        for dev in FLEET:
            ver = self.collector.version_of(dev)
            evts = [e[1] for e in self.collector.events_of(dev)]
            r = self.collector.ota_results.get(dev)
            rows.append((dev, ver, r["outcome"] if r else "-",
                         ",".join(evts) or "-"))
        print(f"  {'device':<18} {'fw':<8} {'last OTA':<18} events")
        for dev, ver, out, evts in rows:
            print(f"  {c(dev, 'bold'):<18} {str(ver):<8} {out:<18} {evts}")

        ok_n = sum(1 for _, ok in self.checks if ok)
        print(f"\n  checks passed: {c(f'{ok_n}/{len(self.checks)}', 'green' if ok_n == len(self.checks) else 'red')}")
        for name, ok in self.checks:
            if not ok:
                self.failures.append(name)

        for dev in list(self.procs):
            try:
                self.stop_device(dev)
            except Exception:
                self.procs[dev][0].kill()
        self.collector.client.loop_stop()
        self.collector.client.disconnect()

        if self.failures:
            print(f"\n{c('FAILED checks:', 'red')}")
            for f in self.failures:
                print(f"  - {f}")
            print(f"\ndevice logs: {LOG_DIR}")
            sys.exit(1)
        print(f"\n{c('ALL CHECKS PASSED — the lab reproduces the future MQTT environment.', 'green')}")
        sys.exit(0)


def broker_up(host, port):
    s = socket.socket()
    s.settimeout(2)
    try:
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description="MQTT lab end-to-end scenario")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--ca",
                    default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", "broker", "certs", "ca.crt"),
                    help="CA cert for TLS (default: relative to this script)")
    ap.add_argument("--fast", action="store_true", help="shrink simulated delays")
    args = ap.parse_args()
    broker_ok = broker_up(args.host, args.port)
    if not broker_ok:
        print("broker not reachable — run scripts/start-broker.sh first")
        sys.exit(2)
    Demo(args, broker_ok).run()


if __name__ == "__main__":
    main()
