#!/usr/bin/env python3
"""MQTT-triggered OTA (AW-006 step ④): the device connects to the mqtt-lab
broker and subscribes to ota/announce; the fleet server publishes a 3.1.0 OTA
notification; the device receives it, offers the candidate, and after a UART
"install" confirmation downloads/verifies/installs and boots 3.1.0.

Broker: aw-mqtt-broker (docker) on host, QEMU reaches it via 10.0.2.2:1883.
Device user: esp32s3-a1b2c3 (from mqtt-lab device-creds.env). Publisher: server.

Run with the mqtt-lab venv python so paho is available:
  experiments/mqtt-lab/.venv/bin/python firmware/test/qemu/scripts/run_mqtt.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qemu_harness as H

SCENARIO = "mqtt-trigger-ota"
BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1883
SERVER_USER = "server"
SERVER_PASS = "srv-dev-pass"


def main():
    run_dir = H.fresh_run_dir(SCENARIO)
    print(f"evidence dir: {run_dir}")
    work_dir = H.WORK_ROOT / SCENARIO
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    flash = work_dir / "qemu_flash.bin"
    shutil.copyfile(H.REPO_ROOT / "build" / "fw-3.0.0" / "merged_16m.bin", flash)

    bin_310 = H.REPO_ROOT / "build" / "fw-3.1.0" / "agent_widget.bin"
    port = H.FIXTURE_PORT
    fixture_root = work_dir / "fixture-root"
    manifest = H.build_fixture_root(fixture_root, "3.1.0", bin_src=bin_310, port=port)
    (run_dir / "fixture-hashes.txt").write_text(json.dumps(manifest, indent=2) + "\n")

    # OTA notification payload per docs/ota/11 (single manifest record)
    notify = {
        "version": "3.1.0",
        "url": manifest["url"],
        "size": manifest["size"],
        "sha256": manifest["sha256"],
        "signature": manifest["signature"],
        "min_version": "0.0.0",
        "id": "mqtt-trigger-test-1",
    }
    (run_dir / "announce.json").write_text(json.dumps(notify, indent=2) + "\n")

    server = H.start_fixture_server(fixture_root, port, run_dir / "server.log")
    try:
        H.wait_https_healthz(port)
        serial_port = H.free_tcp_port()
        qemu = H.start_qemu(flash, serial_port, work_dir / "qemu-monitor.sock", run_dir / "qemu.log")
        serial = H.SerialSession(serial_port, run_dir / "serial.raw.log", run_dir / "serial.log")
        try:
            serial.wait_for(r"event=NET_UP", timeout=60)
            serial.wait_for(r"event=MQTT_START", timeout=30)
            print("device MQTT client started")
            serial.wait_for(r"connected to broker", timeout=60)
            print("device connected to broker (subscribed to ota/announce)")

            # publish the OTA notification with the fleet-server credential
            import paho.mqtt.client as mqtt  # noqa: E402
            pub = mqtt.Client(client_id="lab-server-announce")
            pub.username_pw_set(SERVER_USER, SERVER_PASS)
            pub.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
            pub.loop_start()
            info = pub.publish("ota/announce", json.dumps(notify), qos=1, retain=False)
            info.wait_for_publish(10)
            pub.loop_stop()
            pub.disconnect()
            print("announce published to ota/announce")

            serial.wait_for(r"event=MQTT_NOTIFY result=ok version=3\.1\.0", timeout=30)
            print("device received and parsed the notification")
            line, m, idx = serial.wait_for(r"event=CANDIDATE version=3\.1\.0 .*trigger=mqtt", timeout=15)
            print("candidate offered via MQTT:", line)

            serial.send_line("install")
            serial.wait_for(r"AW_CMD .*result=ok", timeout=10, start_index=idx)
            serial.wait_for(r"event=SHA_OK version=3\.1\.0", timeout=60)
            serial.wait_for(r"event=BOOT_SET version=3\.1\.0", timeout=15)
            serial.wait_for(r"event=REBOOT version=3\.1\.0", timeout=15)
            serial.wait_for(r"event=BOOT version=3\.1\.0 running=ota_0 state=PENDING_VERIFY", timeout=60)
            serial.wait_for(r"event=MARK_VALID version=3\.1\.0", timeout=60)
            print("MQTT-TRIGGER OTA PASS: 3.0.0 -> 3.1.0 via ota/announce")
        finally:
            qemu.sigterm_wait()
            serial.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
