#!/usr/bin/env python3
"""T1 — normal upgrade and confirmation. See codex-architecture.md section 9.

Factory 3.0.0 -> discovers 3.1.0 (correct sha/signature) -> installs ->
reboots PENDING_VERIFY -> self-test passes -> MARK_VALID -> a second,
independent QEMU process restart against the same flash still boots 3.1.0
VALID.
"""
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qemu_harness as H

SCENARIO = "t1-success"


def main():
    run_dir = H.fresh_run_dir(SCENARIO)
    print(f"evidence dir: {run_dir}")

    work_dir = H.WORK_ROOT / SCENARIO
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    flash_path = work_dir / "qemu_flash.bin"
    shutil.copyfile(H.REPO_ROOT / "build" / "fw-3.0.0" / "merged_16m.bin", flash_path)
    flash_before = H.sha256_hex(flash_path)

    port = H.FIXTURE_PORT
    fixture_root = work_dir / "fixture-root"
    manifest = H.build_fixture_root(
        fixture_root, "3.1.0",
        bin_src=H.REPO_ROOT / "build" / "fw-3.1.0" / "agent_widget.bin",
        port=port,
    )
    (run_dir / "fixture-hashes.txt").write_text(json.dumps(manifest, indent=2) + "\n")

    server = H.start_fixture_server(fixture_root, port, run_dir / "server.log")
    try:
        H.wait_https_healthz(port)
        print(f"fixture server healthy on 127.0.0.1:{port}")

        serial_port = H.free_tcp_port()
        monitor_sock = work_dir / "qemu-monitor.sock"
        qemu = H.start_qemu(flash_path, serial_port, monitor_sock, run_dir / "qemu.log")
        serial = H.SerialSession(serial_port, run_dir / "serial.raw.log", run_dir / "serial.log")
        try:
            serial.wait_for(r"event=NET_UP", timeout=60)
            print("NET_UP observed")

            line, m, idx = serial.wait_for(r"event=CANDIDATE version=3\.1\.0", timeout=60)
            print(f"candidate available: {line}")

            serial.send_line("install")
            serial.wait_for(r"AW_CMD .*result=ok", timeout=10, start_index=idx)

            serial.wait_for(r"event=SIGNATURE_OK version=3\.1\.0", timeout=15)
            serial.wait_for(r"event=SHA_OK version=3\.1\.0", timeout=60)
            serial.wait_for(r"event=BOOT_SET version=3\.1\.0", timeout=15)
            serial.wait_for(r"event=REBOOT version=3\.1\.0", timeout=15)

            serial.wait_for(r"event=BOOT version=3\.1\.0 running=ota_0 state=PENDING_VERIFY", timeout=60)
            print("rebooted into ota_0, PENDING_VERIFY confirmed")

            serial.wait_for(r"event=MARK_VALID version=3\.1\.0", timeout=60)
            print("MARK_VALID observed")

            flash_after_markvalid = H.sha256_hex(flash_path)
        finally:
            qemu.sigterm_wait()
            serial.close()

        # Second, independent QEMU process against the same flash file:
        # must still boot 3.1.0 VALID (proves mark-valid persisted in otadata).
        serial_port2 = H.free_tcp_port()
        monitor_sock2 = work_dir / "qemu-monitor-2.sock"
        qemu2 = H.start_qemu(flash_path, serial_port2, monitor_sock2, run_dir / "qemu2.log")
        serial2 = H.SerialSession(serial_port2, run_dir / "serial2.raw.log", run_dir / "serial2.log")
        try:
            serial2.wait_for(r"event=BOOT version=3\.1\.0 running=ota_0 state=VALID", timeout=60)
            print("second boot confirms version=3.1.0 running=ota_0 state=VALID")
        finally:
            qemu2.sigterm_wait()
            serial2.close()

        flash_after = H.sha256_hex(flash_path)
        (run_dir / "flash-before.sha256").write_text(flash_before + "\n")
        (run_dir / "flash-after.sha256").write_text(flash_after + "\n")
        (run_dir / "flash-after-markvalid.sha256").write_text(flash_after_markvalid + "\n")
        (run_dir / "environment.txt").write_text(H.environment_txt({
            "scenario": SCENARIO, "fixture_port": port, "flash_path": flash_path,
        }))
        print("T1 PASS")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
