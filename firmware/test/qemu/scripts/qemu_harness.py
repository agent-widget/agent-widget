#!/usr/bin/env python3
"""qemu_harness.py — shared primitives for the AW-006 QEMU OTA drills (T1-T5).

Not a CLI by itself; imported by the per-scenario driver scripts
(run_t1.py, run_t2.py, ...). Provides:
  - QEMU process launch with a TCP serial socket (for command injection) and
    a Unix monitor socket, per codex-architecture.md section 8.4.
  - SerialSession: background reader thread, raw + normalized log files,
    regex-based wait_for() with a named timeout (no fixed sleeps for success).
  - Fixture root construction (manifest.json / releases/latest / binary) via
    fixture_json.py and sign-firmware.sh.
  - Host-side flash hashing and evidence-directory bookkeeping.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
FW_ROOT = REPO_ROOT / "firmware"
SCRIPTS_DIR = FW_ROOT / "test" / "qemu" / "scripts"
PKI_DIR = FW_ROOT / "test" / "qemu" / "fixtures" / "pki"
EVIDENCE_ROOT = REPO_ROOT / "docs.local" / "operations" / "qemu-ota" / "evidence"
WORK_ROOT = REPO_ROOT / "docs.local" / "operations" / "qemu-ota" / "work"

# CONFIG_AGENT_WIDGET_RELEASES_API_URL / MANIFEST_URL are baked into each
# firmware variant at build time (see sdkconfig.fixture-urls) as
# https://10.0.2.2:FIXTURE_PORT/... — the fixture server MUST listen on this
# exact port for every scenario, since the running binary cannot be told a
# different port at runtime. Scenarios run one at a time, so a fixed port is
# safe (no cross-scenario reuse conflicts).
FIXTURE_PORT = 8443

AW_EVT_RE = re.compile(r"AW_EVT seq=(\d+) event=(\S+)(.*)")


def sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def free_tcp_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def sign_firmware(bin_path: Path, priv_key: Path | None = None) -> tuple[str, str]:
    """Returns (sha256_hex, signature_b64) via sign-firmware.sh."""
    cmd = [str(SCRIPTS_DIR / "sign-firmware.sh"), str(bin_path)]
    if priv_key is not None:
        cmd.append(str(priv_key))
    out = subprocess.check_output(cmd, text=True)
    sha256 = None
    signature = None
    for line in out.splitlines():
        if line.startswith("sha256="):
            sha256 = line.split("=", 1)[1].strip()
        elif line.startswith("signature="):
            signature = line.split("=", 1)[1].strip()
    assert sha256 and signature, f"sign-firmware.sh produced unexpected output: {out!r}"
    return sha256, signature


def build_fixture_root(
    root: Path,
    version: str,
    bin_src: Path,
    port: int,
    *,
    sha256: str | None = None,
    signature: str | None = None,
    priv_key: Path | None = None,
    min_version: str = "0.0.0",
    served_bin: Path | None = None,
) -> dict:
    """Writes api/releases/latest, manifest.json, and releases/<version>/... .

    By default signs bin_src for both the declared digest/signature and the
    served payload. Pass sha256/signature explicitly (still computed from
    bin_src by sign_firmware unless overridden) and/or served_bin to a
    different file to construct T2 (corrupted payload) / T3 (wrong signer)
    fixtures.
    """
    root.mkdir(parents=True, exist_ok=True)
    if sha256 is None or signature is None:
        real_sha256, real_signature = sign_firmware(bin_src, priv_key)
        sha256 = sha256 or real_sha256
        signature = signature or real_signature

    size = os.path.getsize(bin_src)
    asset_name = f"agent_widget-{version}.bin"
    url = f"https://10.0.2.2:{port}/releases/{version}/{asset_name}"

    subprocess.check_call([
        sys.executable, str(SCRIPTS_DIR / "fixture_json.py"), "latest",
        "--out", str(root / "api" / "releases" / "latest"),
        "--version", version,
    ])
    subprocess.check_call([
        sys.executable, str(SCRIPTS_DIR / "fixture_json.py"), "manifest",
        "--out", str(root / "manifest.json"),
        "--version", version,
        "--url", url,
        "--size", str(size),
        "--sha256", sha256,
        "--signature", signature,
        "--min-version", min_version,
    ])

    dest = root / "releases" / version / asset_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(served_bin or bin_src, dest)

    return {"version": version, "url": url, "size": size, "sha256": sha256, "signature": signature}


def start_fixture_server(root: Path, port: int, log_path: Path) -> subprocess.Popen:
    log_f = open(log_path, "w")
    proc = subprocess.Popen(
        [
            sys.executable, str(SCRIPTS_DIR / "fixture_server.py"),
            "--root", str(root),
            "--port", str(port),
            "--cert", str(PKI_DIR / "server_cert.pem"),
            "--key", str(PKI_DIR / "server_key.pem"),
        ],
        stdout=log_f,
        stderr=log_f,
    )
    proc._log_f = log_f  # keep reference alive
    return proc


def wait_https_healthz(port: int, timeout: float = 15.0) -> None:
    """Host-side liveness check only (is the fixture server up and serving
    /healthz over TLS at all). Not the acceptance-relevant certificate
    verification: the QEMU guest's mbedTLS verification against the same
    embedded QEMU_TEST_CA_PEM (see qemu_test_ca.h) is what the tests actually
    assert on via SIGNATURE_OK/CHANNEL_RESULT events. Modern Python/OpenSSL
    enforce RFC 5280 keyUsage strictness on the test CA that mbedTLS does not,
    so a strict host-side verify here would fail for reasons irrelevant to
    device acceptance."""
    ctx = ssl._create_unverified_context()
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=2)
            conn.request("GET", "/healthz")
            resp = conn.getresponse()
            body = resp.read()
            conn.close()
            if resp.status == 200 and body == b"ok":
                return
        except (ConnectionRefusedError, ssl.SSLError, OSError) as e:
            last_err = e
        time.sleep(0.2)
    raise TimeoutError(f"fixture server /healthz not reachable on 127.0.0.1:{port}: {last_err}")


def which_qemu() -> str:
    exe = shutil.which("qemu-system-xtensa")
    if not exe:
        raise RuntimeError("qemu-system-xtensa not on PATH; did you `source activate.sh`?")
    return exe


@dataclass
class QemuProcess:
    proc: subprocess.Popen
    flash_path: Path
    serial_port: int
    monitor_sock: Path
    qemu_log: Path

    def sigkill(self) -> float:
        """Sends SIGKILL, waits for exit, returns wall-clock kill timestamp."""
        t = time.time()
        self.proc.kill()
        self.proc.wait(timeout=10)
        return t

    def sigterm_wait(self, timeout: float = 10) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def start_qemu(flash_path: Path, serial_port: int, monitor_sock: Path, qemu_log: Path) -> QemuProcess:
    if monitor_sock.exists():
        monitor_sock.unlink()
    log_f = open(qemu_log, "w")
    cmd = [
        which_qemu(),
        "-machine", "esp32s3",
        "-nographic",
        "-drive", f"file={flash_path},if=mtd,format=raw",
        "-nic", "user,model=open_eth",
        "-serial", f"tcp:127.0.0.1:{serial_port},server=on,wait=off",
        "-monitor", f"unix:{monitor_sock},server=on,wait=off",
        "-display", "none",
    ]
    log_f.write("cmd: " + " ".join(cmd) + "\n")
    log_f.flush()
    proc = subprocess.Popen(cmd, stdout=log_f, stderr=log_f)
    proc._log_f = log_f
    return QemuProcess(proc=proc, flash_path=flash_path, serial_port=serial_port,
                        monitor_sock=monitor_sock, qemu_log=qemu_log)


class SerialSession:
    """Connects to the QEMU TCP serial port, tees raw bytes to a log file,
    decodes newline-delimited text into a growing list of lines, and lets
    callers wait for a regex match (never a fixed sleep for success)."""

    def __init__(self, port: int, raw_log_path: Path, log_path: Path, connect_timeout: float = 15.0):
        self.port = port
        self._lines: list[str] = []
        self._buf = b""
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._stop = False

        deadline = time.time() + connect_timeout
        last_err = None
        sock = None
        while time.time() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError as e:
                last_err = e
                time.sleep(0.2)
        if sock is None:
            raise TimeoutError(f"could not connect to QEMU serial tcp:127.0.0.1:{port}: {last_err}")
        # socket.create_connection(..., timeout=2) leaves that timeout set on
        # the socket permanently (not just for the connect() call). Left in
        # place, recv() in _reader() raises socket.timeout (an OSError
        # subclass) the first time the guest goes >2s without emitting
        # anything, silently killing the reader thread mid-boot. Must reset
        # to blocking mode before handing off to the reader thread.
        sock.settimeout(None)
        self._sock = sock

        self._raw_f = open(raw_log_path, "wb")
        self._log_f = open(log_path, "w")
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while not self._stop:
            try:
                data = self._sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            self._raw_f.write(data)
            self._raw_f.flush()
            with self._lock:
                self._buf += data
                while b"\n" in self._buf:
                    line, self._buf = self._buf.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace").rstrip("\r")
                    self._lines.append(text)
                    self._log_f.write(text + "\n")
                    self._log_f.flush()
                self._cv.notify_all()

    def send_line(self, s: str) -> None:
        self._sock.sendall((s + "\n").encode("utf-8"))
        self._log_f.write(f">>> {s}\n")
        self._log_f.flush()

    def wait_for(self, pattern: str, timeout: float = 30.0, start_index: int = 0) -> tuple[str, re.Match, int]:
        """Blocks until a line at/after start_index matches `pattern` (re.search).
        Returns (line, match, index_of_matching_line). Raises TimeoutError."""
        regex = re.compile(pattern)
        deadline = time.time() + timeout
        with self._lock:
            idx = start_index
            while True:
                while idx < len(self._lines):
                    m = regex.search(self._lines[idx])
                    if m:
                        return self._lines[idx], m, idx
                    idx += 1
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"timed out waiting for /{pattern}/ (timeout={timeout}s); "
                                        f"last lines: {self._lines[-10:]}")
                self._cv.wait(timeout=remaining)

    def line_count(self) -> int:
        with self._lock:
            return len(self._lines)

    def all_lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def close(self):
        self._stop = True
        with contextlib.suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            self._sock.close()
        self._thread.join(timeout=5)
        self._raw_f.close()
        self._log_f.close()


def fresh_run_dir(scenario: str) -> Path:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    d = EVIDENCE_ROOT / scenario / ts
    d.mkdir(parents=True, exist_ok=False)
    return d


def environment_txt(extra: dict) -> str:
    git_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()
    idf_ver = subprocess.run(["idf.py", "--version"], capture_output=True, text=True).stdout.strip()
    qemu_ver = subprocess.run([which_qemu(), "--version"], capture_output=True, text=True).stdout.strip().splitlines()[0]
    lines = [f"git_sha={git_sha}", f"idf_version={idf_ver}", f"qemu_version={qemu_ver}"]
    for k, v in extra.items():
        lines.append(f"{k}={v}")
    return "\n".join(lines) + "\n"
