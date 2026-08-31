#!/usr/bin/env python3
"""T3 — wrong signer. Manifest sha256 is correct for the served payload, but the
signature was produced with an attacker key → SIGNATURE_FAIL, install rejected."""
import json, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import qemu_harness as H

SCENARIO = "t3-bad-signature"


def main():
    run_dir = H.fresh_run_dir(SCENARIO)
    print(f"evidence dir: {run_dir}")
    work_dir = H.WORK_ROOT / SCENARIO
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    flash = work_dir / "qemu_flash.bin"
    shutil.copyfile(H.REPO_ROOT / "build" / "fw-3.0.0" / "merged_16m.bin", flash)

    # attacker keypair (throwaway)
    attacker_priv = work_dir / "attacker_priv.pem"
    subprocess.check_call(["openssl", "genrsa", "-out", str(attacker_priv), "2048"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    bin_src = H.REPO_ROOT / "build" / "fw-3.1.0" / "agent_widget.bin"
    port = H.FIXTURE_PORT
    fixture_root = work_dir / "fixture-root"
    manifest = H.build_fixture_root(fixture_root, "3.1.0", bin_src=bin_src, port=port,
                                    priv_key=attacker_priv)
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
            line = serial.wait_for(r"event=SIGNATURE_FAIL version=3\.1\.0", timeout=15)
            print("SIGNATURE_FAIL observed:", line)
            serial.wait_for(r"event=CHECK_BEGIN", timeout=30)
            print("T3 PASS: wrong-signer firmware rejected, device stayed on 3.0.0")
        finally:
            qemu.sigterm_wait()
            serial.close()
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    main()
