#!/usr/bin/env python3
"""T4 — self-test forced failure → automatic rollback.

Installs 3.2.0 (built with SELFTEST_FORCE_FAIL). After reboot the image is
PENDING_VERIFY; boot_health's forced-failure self-test must call
esp_ota_mark_app_invalid_rollback_and_reboot(); the device comes back on the
previous firmware (3.0.0 factory)."""
import json, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qemu_harness as H

SCENARIO = "t4-selftest-rollback"


def main():
    run_dir = H.fresh_run_dir(SCENARIO)
    print(f"evidence dir: {run_dir}")
    work_dir = H.WORK_ROOT / SCENARIO
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    flash = work_dir / "qemu_flash.bin"
    shutil.copyfile(H.REPO_ROOT / "build" / "fw-3.0.0" / "merged_16m.bin", flash)

    bin_320 = H.REPO_ROOT / "build" / "fw-3.2.0" / "agent_widget.bin"
    port = H.FIXTURE_PORT
    fixture_root = work_dir / "fixture-root"
    manifest = H.build_fixture_root(fixture_root, "3.2.0", bin_src=bin_320, port=port)
    (run_dir / "fixture-hashes.txt").write_text(json.dumps(manifest, indent=2) + "\n")

    server = H.start_fixture_server(fixture_root, port, run_dir / "server.log")
    try:
        H.wait_https_healthz(port)
        serial_port = H.free_tcp_port()
        qemu = H.start_qemu(flash, serial_port, work_dir / "qemu-monitor.sock", run_dir / "qemu.log")
        serial = H.SerialSession(serial_port, run_dir / "serial.raw.log", run_dir / "serial.log")
        try:
            serial.wait_for(r"event=NET_UP", timeout=60)
            line, m, idx = serial.wait_for(r"event=CANDIDATE version=3\.2\.0", timeout=60)
            print("candidate:", line)
            serial.send_line("install")
            serial.wait_for(r"AW_CMD .*result=ok", timeout=10, start_index=idx)
            serial.wait_for(r"event=SHA_OK version=3\.2\.0", timeout=60)
            serial.wait_for(r"event=BOOT_SET version=3\.2\.0", timeout=15)
            serial.wait_for(r"event=REBOOT version=3\.2\.0", timeout=15)
            # new image boots PENDING_VERIFY, self-test forced fail
            serial.wait_for(r"event=BOOT version=3\.2\.0 running=ota_0 state=PENDING_VERIFY", timeout=60)
            print("booted into 3.2.0 PENDING_VERIFY")
            serial.wait_for(r"event=SELFTEST_BEGIN", timeout=15)
            line = serial.wait_for(r"event=MARK_INVALID version=3\.2\.0", timeout=60)
            print("MARK_INVALID observed:", line)
            # rolled back onto the previous firmware
            serial.wait_for(r"event=BOOT version=3\.0\.0", timeout=60)
            print("T4 PASS: forced self-test failure rolled back to 3.0.0")
        finally:
            qemu.sigterm_wait()
            serial.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
