"""Dnsmasq-DHCP 升級測試的資料檢查（pipeline release-gating/180）。

Store 的升級測試（Woow_HA_App_Store .addon-sync/upgrade_runtime.py）在比對對象
（最新 Release）上跑 `seed`，再用同一份 `/data` 啟動新版本、跑 `verify`。兩支 hook
都在 mock Supervisor 的容器裡執行。

dnsmasq 沒有寫入租約的 API，租約只會來自真的 DHCP 請求，所以負責人 2026-11-09
核准 #90 標準的例外（方案 b）：

seed     在 $DATA_DIR_DATA/dnsmasq.leases 以檔案層級加一行租約（MAC、IP 在設定的
         DHCP pool 裡、到期時間遠在未來，dnsmasq 啟動時不會把它當過期租約刪掉），
         再透過 app 自己的 websocket（web UI 後端 /ws，port 為 options 的
         web_ui.port，預設 8976）確認後端讀到了這筆租約。
verify   在新版本上透過同一個 /ws 讀回同一筆租約（MAC、IP、hostname、到期時間都
         不變）。新版的 dnsmasq 啟動時會讀並重寫租約檔，後端再從租約檔讀出，所以
         讀得回來代表新版的 dnsmasq 與後端都接受舊版的租約檔。

web UI 後端只有 `/`、`/static/`、`/ws`；/ws 連上後立刻推一則 JSON
（current_clients、past_clients...，見上游 backend/pkg/uibackend/types.go）。
這裡用標準函式庫寫一個最小的 websocket client。seed 寫的值存在 HOOK_STATE_DIR。
每項檢查寫進 $REPORT_DIR/<hook>.json；有任何一項 fail，hook 就 exit 1。
只用標準函式庫（hook 跑在 python:3.12-alpine）。
"""
from __future__ import annotations

import base64
import ipaddress
import json
import os
import socket
import struct
import sys
import time

# 本機管理（locally administered）的 MAC，不會撞到真的網卡。
LEASE_MAC = "02:57:4f:4f:57:b4"
LEASE_HOSTNAME = "woow-upgrade-check"
# 2100-01-01T00:00:00Z：遠在未來，dnsmasq 不會當成過期租約。
LEASE_EXPIRES = 4102444800
# pool 起點往後的位移（pool 至少要有這麼大；預設 pool 是 .50–.150）。
POOL_OFFSET = 27
DEFAULT_WEB_UI_PORT = 8976
READY_TIMEOUT = 240
SEEN_TIMEOUT = 60


def options() -> dict:
    with open(os.path.join(os.environ["DATA_DIR_DATA"], "options.json"), encoding="utf-8") as f:
        return json.load(f)


def ws_port(opts: dict) -> int:
    return int((opts.get("web_ui") or {}).get("port") or DEFAULT_WEB_UI_PORT)


def lease_ip(opts: dict) -> str:
    """設定的第一個 DHCP pool 裡的一個位址（pool 起點 + POOL_OFFSET，超出 pool 時用起點）。"""
    pools = opts.get("dhcp_pools") or []
    assert pools, "options.json has no dhcp_pools"
    start, end = ipaddress.IPv4Address(pools[0]["start"]), ipaddress.IPv4Address(pools[0]["end"])
    ip = start + POOL_OFFSET
    return str(ip if ip <= end else start)


def lease_file() -> str:
    return os.path.join(os.environ["DATA_DIR_DATA"], "dnsmasq.leases")


def state_path() -> str:
    return os.path.join(os.environ["HOOK_STATE_DIR"], "dnsmasq-seed.json")


# --- minimal websocket client (RFC 6455, client side, text messages only) ---

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("connection closed by the server")
        buf += chunk
    return buf


def _send_frame(sock: socket.socket, opcode: int, payload: bytes = b"") -> None:
    mask = os.urandom(4)
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 1 << 16:
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))


def ws_first_message(host: str, port: int, path: str = "/ws", timeout: float = 15) -> dict:
    """Connect to ws://host:port/path, return the first text message the server pushes, parsed as JSON."""
    sock = socket.create_connection((host, port), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                      f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError(f"connection closed during the handshake: {head[:200]!r}")
            head += chunk
            assert len(head) < 65536, "handshake answer too long"
        head, rest = head.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0].decode(errors="replace")
        assert " 101 " in status + " ", f"handshake answered {status!r}"
        pending = rest
        message = b""
        while True:
            def take(n: int) -> bytes:
                nonlocal pending
                if len(pending) >= n:
                    out, pending = pending[:n], pending[n:]
                    return out
                out, pending = pending + _recv_exact(sock, n - len(pending)), b""
                return out
            b0, b1 = take(2)
            fin, opcode, masked, n = b0 & 0x80, b0 & 0x0F, b1 & 0x80, b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", take(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", take(8))[0]
            mask = take(4) if masked else b""
            payload = take(n)
            if masked:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x8:
                raise ConnectionError(f"server closed the websocket: {payload[:200]!r}")
            if opcode == 0x9:
                _send_frame(sock, 0xA, payload)
                continue
            if opcode in (0x1, 0x2, 0x0):
                message += payload
                if fin:
                    break
        try:
            _send_frame(sock, 0x8, struct.pack("!H", 1000))
        except OSError:
            pass
        return json.loads(message)
    finally:
        sock.close()


def wait_message(host: str, port: int, wanted=None, timeout: float = READY_TIMEOUT) -> dict:
    """Poll /ws until it answers (and, with `wanted`, until wanted(message) is true); the last message."""
    deadline, last = time.monotonic() + timeout, "no attempt"
    while time.monotonic() < deadline:
        try:
            msg = ws_first_message(host, port)
            if wanted is None or wanted(msg):
                return msg
            last = f"answered, but without the lease: {summary(msg)}"
        except Exception as error:  # noqa: BLE001 - keep polling, report the last reason
            last = f"{type(error).__name__}: {error}"
        time.sleep(2)
    raise AssertionError(f"ws://{host}:{port}/ws after {int(timeout)} s: {last}")


def summary(msg: dict) -> str:
    current = msg.get("current_clients") or []
    return f"{len(current)} current client(s): " + ", ".join(
        f"{(c.get('lease') or {}).get('mac_addr')}={(c.get('lease') or {}).get('ip_addr')}" for c in current[:10])


def find_lease(msg: dict, mac: str) -> dict | None:
    for c in msg.get("current_clients") or []:
        lease = c.get("lease") or {}
        if str(lease.get("mac_addr", "")).lower() == mac.lower():
            return lease
    return None


class Checks:
    """每項檢查都會跑；依賴的前一項失敗時記為 skip，報告裡仍看得到失敗的那一項。"""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def run(self, name: str, check, needs: bool = True) -> object:
        if not needs:
            self.items.append({"name": name, "result": "skip", "detail": "an earlier check it needs failed"})
            print(f"skip {name}", flush=True)
            return None
        try:
            value = check()
        except Exception as error:  # noqa: BLE001 - 每個例外都記成一項失敗與原因
            self.items.append({"name": name, "result": "fail", "detail": f"{type(error).__name__}: {error}"[:500]})
            print(f"FAIL {name}: {error}", flush=True)
            return None
        detail = value if isinstance(value, str) else "ok"
        self.items.append({"name": name, "result": "pass", "detail": detail})
        print(f"pass {name}: {detail}", flush=True)
        return value if value is not None else True

    def finish(self, hook: str) -> int:
        with open(os.path.join(os.environ["REPORT_DIR"], f"{hook}.json"), "w", encoding="utf-8") as f:
            json.dump({"checks": self.items}, f, indent=1)
        return 1 if any(c["result"] != "pass" for c in self.items) else 0


def show_lease_file() -> None:
    try:
        with open(lease_file(), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError as error:
        text = f"<unreadable: {error}>"
    print(f"--- {lease_file()} ---\n{text}--- end ---", flush=True)


def seed() -> int:
    checks, host = Checks(), os.environ["ADDON_HOST"]
    opts = checks.run("options.json readable", options)
    port = ws_port(opts) if opts else DEFAULT_WEB_UI_PORT
    ip = checks.run("lease address in the DHCP pool", lambda: lease_ip(opts), bool(opts))
    ready = checks.run("web UI backend answers on /ws", lambda: summary(wait_message(host, port)), bool(opts))
    lease = {"expires": LEASE_EXPIRES, "mac_addr": LEASE_MAC, "ip_addr": ip, "hostname": LEASE_HOSTNAME}

    def write() -> str:
        # In place (append, no rename): the backend watches this file with inotify.
        line = f"{LEASE_EXPIRES} {LEASE_MAC} {ip} {LEASE_HOSTNAME} 01:{LEASE_MAC}\n"
        path = lease_file()
        with open(path, "a+", encoding="utf-8") as f:
            f.seek(0)
            existing = f.read()
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line)
        with open(state_path(), "w", encoding="utf-8") as f:
            json.dump(lease, f)
        return f"appended {line.strip()!r} to {path}"
    written = checks.run("lease written to dnsmasq.leases (file level, #90 exception)", write, bool(ready) and bool(ip))

    def seen() -> str:
        msg = wait_message(host, port, lambda m: find_lease(m, LEASE_MAC) is not None, SEEN_TIMEOUT)
        return f"/ws lists {find_lease(msg, LEASE_MAC)}"
    checks.run("the app's /ws lists the seeded lease", seen, bool(written))
    show_lease_file()
    return checks.finish("seed")


def verify() -> int:
    checks, host = Checks(), os.environ["ADDON_HOST"]

    def read_state() -> dict:
        try:
            with open(state_path(), encoding="utf-8") as f:
                loaded = json.load(f)
        except (OSError, ValueError) as error:
            raise AssertionError(f"seed state {state_path()} unreadable (did seed run?): {error}") from error
        assert isinstance(loaded, dict) and loaded.get("mac_addr"), f"seed state is {loaded!r}"
        return loaded
    want = checks.run("seed state readable", read_state)
    opts = checks.run("options.json readable", options)
    port = ws_port(opts) if opts else DEFAULT_WEB_UI_PORT
    ready = checks.run("web UI backend answers on /ws (new version started)", lambda: summary(wait_message(host, port)), bool(opts))

    def kept() -> str:
        mac = want["mac_addr"]
        try:
            msg = wait_message(host, port, lambda m: find_lease(m, mac) is not None, SEEN_TIMEOUT)
        except AssertionError as error:
            raise AssertionError(f"the seeded lease {mac} is not listed: {error}") from error
        got = find_lease(msg, mac)
        diff = {k: (want[k], got.get(k)) for k in ("ip_addr", "hostname", "expires") if str(got.get(k)) != str(want[k])}
        assert not diff, f"lease {mac} changed (seeded, now): {diff}"
        return f"/ws lists {got}"
    checks.run("the seeded lease is still listed by /ws, unchanged", kept, bool(want) and bool(ready))
    show_lease_file()
    return checks.finish("verify")


def main(hook: str) -> None:
    sys.exit({"seed": seed, "verify": verify}[hook]())
