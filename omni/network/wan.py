"""
广域网访问：Cloudflare 隧道（vendor/cloudflared）常驻守护 + 本地 DNS 助手。

大陆网络下踩的坑（2026-09 实测）：
  1. argotunnel.com 的 SRV 记录解析被污染 → cloudflared 发现不了边缘 IP，
     "failed to resolve any edge address" 直接退出；
  2. 到边缘 7844 的 TCP / HTTP2 握手会被重置（"TLS handshake with edge error: EOF"）；
  3. 只有 QUIC(UDP:7844) 能连上。
对策：写死边缘 IP 绕过 DNS 发现 + 强制 --protocol quic；本地 DNS 助手劫持 argotunnel.com
的 SRV 查询。实测这组边缘 IP 能注册满 4 条隧道连接。
"""
import os
import socket
import struct
import subprocess
import threading
import time

from omni.core import paths, process, settings
from omni.core.log import log
from omni.network import state

CLOUDFLARE_EDGE_IPS = [
    "198.41.192.7", "198.41.192.27", "198.41.192.37", "198.41.192.47",
    "198.41.192.67", "198.41.192.107", "198.41.192.167", "198.41.192.227",
    "198.41.200.13", "198.41.200.23", "198.41.200.33", "198.41.200.43",
    "198.41.200.53", "198.41.200.113", "198.41.200.193", "198.41.200.233",
]
DNS_HELPER_ADDR = ("127.0.0.1", 53535)
UPSTREAM_DNS = ("223.5.5.5", 53)

_enabled = bool(state.load().get("wan", False))
_proc = None
_proc_lock = threading.Lock()
_dns_started = False


def domain():
    return settings.get("wan_domain")


def enabled() -> bool:
    return _enabled


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)
    state.save(wan=_enabled)


def binary_ready() -> bool:
    if not os.path.exists(paths.CLOUDFLARED_BIN):
        return False
    try:
        res = subprocess.run([paths.CLOUDFLARED_BIN, "--version"], capture_output=True, timeout=2)
        return res.returncode == 0
    except Exception:
        return False


def status() -> dict:
    d = domain()
    return {
        "enabled": _enabled,
        "status": "running" if _enabled else "stopped",
        "url": f"https://{d}" if d else None,
        "domain": d,
        "has_binary": binary_ready(),
    }


def _dns_worker():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(DNS_HELPER_ADDR)
    except Exception:
        return
    while True:
        try:
            data, addr = s.recvfrom(2048)
            if not data:
                break
            tid, qname, idx = data[:2], "", 12
            while idx < len(data):
                n = data[idx]
                if n == 0:
                    idx += 1
                    break
                idx += 1
                qname += data[idx:idx + n].decode("utf-8", "ignore") + "."
                idx += n
            qtype = struct.unpack(">H", data[idx:idx + 2])[0]
            if qtype == 33 and "argotunnel.com" in qname:
                resp_hdr = tid + b"\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00"
                question = data[12:idx + 4]
                target = b"\x07region1\x02v2\x0bargotunnel\x03com\x00"
                rdata = struct.pack(">HHH", 0, 100, 7844) + target
                ans = b"\xc0\x0c\x00\x21\x00\x01\x00\x00\x01\x2c" + struct.pack(">H", len(rdata)) + rdata
                s.sendto(resp_hdr + question + ans, addr)
            else:
                f = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                f.settimeout(2)
                try:
                    f.sendto(data, UPSTREAM_DNS)
                    rdata, _ = f.recvfrom(2048)
                    s.sendto(rdata, addr)
                except Exception:
                    pass
                finally:
                    f.close()
        except Exception:
            pass


def _start_dns_helper():
    global _dns_started
    if not _dns_started:
        _dns_started = True
        threading.Thread(target=_dns_worker, daemon=True, name="wan-dns").start()


def start_daemon() -> None:
    """后台常驻：开关打开时拉起并保持 cloudflared 隧道，关着时空闲等待。"""
    config_file = settings.tool("cloudflared_config")
    if not binary_ready() or not os.path.exists(config_file):
        return
    _start_dns_helper()

    def worker():
        global _proc
        while True:
            if not _enabled:
                time.sleep(10)
                continue
            try:
                cmd = [paths.CLOUDFLARED_BIN, "--config", config_file, "--protocol", "quic"]
                for ip in CLOUDFLARE_EDGE_IPS:
                    cmd += ["--edge", f"{ip}:7844"]
                cmd += ["tunnel", "run"]
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        preexec_fn=process.set_pdeathsig)
                with _proc_lock:
                    _proc = proc
                proc.wait()
            except Exception as e:
                log("WARN", f"Cloudflare 隧道守护异常: {e}", tag="WAN")
            time.sleep(3)

    threading.Thread(target=worker, daemon=True, name="wan-tunnel").start()
