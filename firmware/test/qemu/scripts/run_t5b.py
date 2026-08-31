#!/usr/bin/env python3
"""T5 — power loss mid-download. SIGKILL QEMU while the body is streaming; a
fresh QEMU process against the same flash must boot the OLD firmware (3.0.0) —
otadata was never flipped, so nothing is bricked and the update can be retried."""
import json, shutil, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qemu_harness as H

SCENARIO = "t5-power-loss"


def main():
    run_dir = H.fresh_run_dir(SCENARIO)
    print(f"evidence dir: {run_dir}")
    work_dir = H.WORK_ROOT / SCENARIO
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    flash = work_dir / "qemu_flash.bin"
    shutil.copyfile(H.REPO_ROOT / "build" / "fw-3.0.0" / "merged_16m.bin", flash)
    flash_before = H.sha256_hex(flash)

    bin_src = H.REPO_ROOT / "build" / "fw-3.1.0" / "agent_widget.bin"
    port = H.FIXTURE_PORT
    fixture_root = work_dir / "fixture-root"
    manifest = H.build_fixture_root(fixture_root, "3.1.0", bin_src=bin_src, port=port)
    (run_dir / "fixture-hashes.txt").write_text(json.dumps(manifest, indent=2) + "\n")

    server = H.start_fixture_server(fixture_root, port, run_dir / "server.log")
    try:
        H.wait_https_healthz(port)
        serial_port = H.free_tcp_port()
        qemu = H.start_qemu(flash, serial_port, work_dir / "qemu-monitor.sock", run_dir / "qemu.log")
        serial = H.SerialSession(serial_port, run_dir / "serial.raw.log", run_dir / "serial.log")
        try:
            serial.wait_for(r"event=NET_UP", timeout=60)
            line, m, idx = serial.wait_for(r"event=CANDIDATE version=3\.1\.0", timeout=60)
            print("candidate:", line)
            serial.send_line("install")
            serial.wait_for(r"AW_CMD .*result=ok", timeout=10, start_index=idx)
            # wait until the body is streaming, then kill the power
            serial.wait_for(r"event=DOWNLOAD_PROGRESS", timeout=60)
            print("download in progress — killing QEMU (power loss)")
            qemu.sigkill()
            serial.close()
        finally:
            try:
                serial.close()
            except Exception:
                pass

        # relaunch a fresh QEMU against the same flash file
        serial_port2 = H.free_tcp_port()
        qemu2 = H.start_qemu(flash, serial_port2, work_dir / "qemu-monitor-2.sock", run_dir / "qemu2.log")
        serial2 = H.SerialSession(serial_port2, run_dir / "serial2.raw.log", run_dir / "serial2.log")
        try:
            serial2.wait_for(r"event=BOOT version=3\.0\.0", timeout=60)
            print("post-power-loss boot confirmed: version=3.0.0 (old firmware)")
            serial2.wait_for(r"event=NET_UP", timeout=60)
            print("T5 PASS: power loss mid-download did not brick the device")
        finally:
            qemu2.sigterm_wait()
            serial2.close()

        flash_after = H.sha256_hex(flash)
        (run_dir / "flash-before.sha256").write_text(flash_before + "\n")
        (run_dir / "flash-after.sha256").write_text(flash_after + "\n")
        (run_dir / "environment.txt").write_text(H.environment_txt({
            "scenario": SCENARIO, "fixture_port": port, "flash_path": flash,
        }))
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
