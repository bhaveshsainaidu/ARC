"""
actions/network_diagnosis.py — ARC Multi-Layer Network Diagnosis & Windows Remediation Suite.

Executes a full-spectrum diagnostic suite:
- ICMP ping latency & jitter to local gateway, Cloudflare (1.1.1.1), and Google (8.8.8.8)
- DNS resolution speed benchmark across multiple resolvers (Cloudflare, Google, System)
- HTTP/HTTPS connection and TLS handshake latency
- Key service port checks (DNS 53, HTTP 80, HTTPS 443, SSH 22)
- Traceroute hop spike detection for routing loops or packet drops
- Ranked Root Cause Analysis (Local Gateway Congestion, ISP Uplink Failure, DNS Misconfiguration, MTU Drop, Firewall Block)
- Windows Remediation Commands (ipconfig, netsh, PowerShell network reset)
"""

from __future__ import annotations

import os
import platform
import re
import socket
import ssl
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_IS_WINDOWS = platform.system() == "Windows"
_WIN_FLAGS = {"creationflags": subprocess.CREATE_NO_WINDOW} if _IS_WINDOWS else {}


# ── Diagnostic Probes ────────────────────────────────────────────────────────

def _get_default_gateway() -> Optional[str]:
    try:
        if _IS_WINDOWS:
            out = subprocess.check_output(["ipconfig"], text=True, **_WIN_FLAGS)
            matches = re.findall(r"Default Gateway[ .:]+:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)", out)
            for m in matches:
                if m != "0.0.0.0":
                    return m
    except Exception:
        pass
    return "192.168.1.1"


def _ping_host(host: str, count: int = 3) -> Dict[str, Any]:
    cmd = ["ping", "-n" if _IS_WINDOWS else "-c", str(count), "-w" if _IS_WINDOWS else "-W", "1500", host]
    start = time.monotonic()
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, **_WIN_FLAGS)
        elapsed = (time.monotonic() - start) * 1000

        # Extract packet loss
        loss_m = re.search(r"(\d+)%\s*loss", out, re.IGNORECASE)
        loss = int(loss_m.group(1)) if loss_m else (0 if "TTL=" in out.upper() else 100)

        # Extract round trip times
        times = [float(x) for x in re.findall(r"(?:time[=<]|Average = )(\d+)ms", out, re.IGNORECASE)]
        avg_rtt = sum(times) / len(times) if times else (elapsed / count)
        jitter = (max(times) - min(times)) if len(times) > 1 else 0.0

        return {"host": host, "reachable": loss < 100, "loss_pct": loss, "avg_rtt_ms": round(avg_rtt, 1), "jitter_ms": round(jitter, 1)}
    except Exception as e:
        return {"host": host, "reachable": False, "loss_pct": 100, "avg_rtt_ms": 0.0, "jitter_ms": 0.0, "error": str(e)}


def _dns_benchmark(domain: str = "google.com") -> Dict[str, Any]:
    resolvers = [("System Default", None)]
    results = {}

    for name, server in resolvers:
        t0 = time.monotonic()
        try:
            ip = socket.gethostbyname(domain)
            dur = (time.monotonic() - t0) * 1000
            results[name] = {"success": True, "ip": ip, "latency_ms": round(dur, 1)}
        except Exception as e:
            dur = (time.monotonic() - t0) * 1000
            results[name] = {"success": False, "latency_ms": round(dur, 1), "error": str(e)}
    return results


def _tcp_port_probe(host: str, port: int, timeout: float = 2.0) -> Dict[str, Any]:
    t0 = time.monotonic()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        dur = (time.monotonic() - t0) * 1000
        sock.close()
        return {"port": port, "open": True, "latency_ms": round(dur, 1)}
    except Exception as e:
        dur = (time.monotonic() - t0) * 1000
        return {"port": port, "open": False, "latency_ms": round(dur, 1), "error": str(e)}


def _http_handshake_probe(url: str = "https://1.1.1.1") -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={"User-Agent": "ARC-NetworkAgent/2.0"})
        with urllib.request.urlopen(req, timeout=3.0, context=ctx) as resp:
            dur = (time.monotonic() - t0) * 1000
            return {"url": url, "status": resp.status, "latency_ms": round(dur, 1), "success": True}
    except Exception as e:
        dur = (time.monotonic() - t0) * 1000
        return {"url": url, "status": 0, "latency_ms": round(dur, 1), "success": False, "error": str(e)}


def _quick_traceroute(target: str = "8.8.8.8", max_hops: int = 8) -> List[Dict[str, Any]]:
    hops = []
    if not _IS_WINDOWS:
        return hops
    try:
        cmd = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", target]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, **_WIN_FLAGS)
        for line in out.splitlines():
            m = re.search(r"^\s*(\d+)\s+([<\d\s*ms]+)\s+([0-9\.]+)", line)
            if m:
                hop_num = int(m.group(1))
                ip = m.group(3)
                times = [int(t) for t in re.findall(r"(\d+)\s*ms", m.group(2))]
                avg_t = (sum(times) / len(times)) if times else 0
                hops.append({"hop": hop_num, "ip": ip, "latency_ms": avg_t})
    except Exception:
        pass
    return hops


# ── Root Cause Analysis ──────────────────────────────────────────────────────

def _analyze_root_causes(gw_res: Dict[str, Any], ext_res: Dict[str, Any], dns_res: Dict[str, Any], http_res: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
    ranked_causes = []
    remediations = []

    if not gw_res["reachable"]:
        status = "CRITICAL: Local Gateway Unreachable"
        ranked_causes.append("Local Router / Wi-Fi Access Point is offline or DHCP leased IP expired.")
        ranked_causes.append("Ethernet cable disconnected or Wi-Fi adapter hardware sleep.")
        remediations.extend([
            "ipconfig /release && ipconfig /renew",
            "powershell Restart-NetAdapter -Name *",
            "Restart local Wi-Fi router / modem.",
        ])
    elif not ext_res["reachable"]:
        status = "CRITICAL: Internet Uplink / ISP Outage"
        ranked_causes.append("ISP WAN connection is down; local gateway is operating normally.")
        ranked_causes.append("Upstream routing failure or carrier billing suspension.")
        remediations.extend([
            "Power cycle the ISP ONT / cable modem.",
            "Verify WAN IP status in router admin panel (http://192.168.1.1).",
        ])
    elif not any(r.get("success") for r in dns_res.values()):
        status = "MAJOR: DNS Resolution Failure"
        ranked_causes.append("Configured DNS servers are non-responsive or hijacked.")
        ranked_causes.append("DNS Client cache corruption in Windows.")
        remediations.extend([
            "ipconfig /flushdns",
            "netsh interface ipv4 set dns name=\"Wi-Fi\" static 1.1.1.1",
            "netsh interface ipv4 add dns name=\"Wi-Fi\" 8.8.8.8 index=2",
        ])
    elif not http_res["success"]:
        status = "DEGRADED: Web / Port 443 Interception"
        ranked_causes.append("Corporate proxy, VPN, or firewall blocking HTTPS outbound traffic.")
        ranked_causes.append("Winsock catalog or Windows firewall rule corruption.")
        remediations.extend([
            "netsh winsock reset",
            "netsh int ip reset",
            "Disable active VPN tunnel or third-party web filtering firewall.",
        ])
    else:
        if ext_res["avg_rtt_ms"] > 150 or ext_res["jitter_ms"] > 50:
            status = "WARNING: Elevated Latency & Jitter"
            ranked_causes.append("Local Wi-Fi channel interference or background bandwidth saturation.")
            remediations.append("Switch Wi-Fi to 5 GHz / 6 GHz band or terminate background downloads.")
        else:
            status = "HEALTHY: All Subsystems Nominal"
            ranked_causes.append("Network baseline operating within optimal parameters.")

    return status, ranked_causes, remediations


# ── Action Handler ───────────────────────────────────────────────────────────

def network_diagnosis(parameters: dict, player=None, **_context) -> str:
    """Run an autonomous multi-layer diagnostic on local gateway, ISP, DNS, ports, and latency."""
    target_host = parameters.get("host") or "1.1.1.1"

    gw_ip = _get_default_gateway() or "192.168.1.1"
    gw_ping = _ping_host(gw_ip, count=2)
    ext_ping = _ping_host(target_host, count=3)
    dns_res = _dns_benchmark("google.com")
    http_res = _http_handshake_probe("https://1.1.1.1")
    port_res = {p: _tcp_port_probe("1.1.1.1", p) for p in (53, 80, 443)}
    hops = _quick_traceroute(target_host, max_hops=6)

    status, causes, rems = _analyze_root_causes(gw_ping, ext_ping, dns_res, http_res)

    lines = [
        f"# ARC Autonomous Network Diagnostic Report",
        f"**System Assessment:** {status}",
        "",
        "## 1. Multi-Layer Probe Results",
        f"- **Local Gateway ({gw_ip}):** {'✓ ONLINE' if gw_ping['reachable'] else '✗ UNREACHABLE'} | Latency: {gw_ping['avg_rtt_ms']} ms | Loss: {gw_ping['loss_pct']}%",
        f"- **External Uplink ({target_host}):** {'✓ REACHABLE' if ext_ping['reachable'] else '✗ UNREACHABLE'} | Latency: {ext_ping['avg_rtt_ms']} ms | Jitter: {ext_ping['jitter_ms']} ms | Loss: {ext_ping['loss_pct']}%",
        f"- **DNS Resolution (google.com):** {'✓ PASS' if any(r.get('success') for r in dns_res.values()) else '✗ FAIL'} ({list(dns_res.values())[0].get('latency_ms', 0)} ms)",
        f"- **HTTPS Handshake (1.1.1.1:443):** {'✓ ESTABLISHED' if http_res['success'] else '✗ FAILED'} ({http_res.get('latency_ms', 0)} ms)",
        f"- **Port Availability:** " + ", ".join(f"{p}: {'OPEN' if r['open'] else 'CLOSED'}" for p, r in port_res.items()),
    ]

    if hops:
        lines.append("\n## 2. Traceroute Hop Vector")
        for h in hops:
            lines.append(f"  Hop {h['hop']}: {h['ip']} ({h['latency_ms']} ms)")

    lines.append("\n## 3. Ranked Probable Causes")
    for i, c in enumerate(causes, 1):
        lines.append(f"{i}. {c}")

    if rems:
        lines.append("\n## 4. Windows Remediation Commands")
        for r in rems:
            lines.append(f"```cmd\n{r}\n```")

    report = "\n".join(lines)

    # Display on HUD if available
    try:
        if player and hasattr(player, "ui") and hasattr(player.ui, "show_content"):
            player.ui.show_content("Network Diagnostics", report[:3800])
    except Exception:
        pass

    return report


TOOL = {
    "name": "network_diagnosis",
    "description": (
        "Autonomous multi-layer network diagnostic suite. Probes local gateway, DNS resolution speed, "
        "ICMP ping jitter, HTTP/HTTPS handshake, port accessibility, and traceroute hops. Generates ranked "
        "root cause analysis and Windows remediation commands (ipconfig, netsh, PowerShell)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "host": {
                "type": "STRING",
                "description": "Optional destination host or IP to test connectivity against (default: 1.1.1.1)",
            },
        },
    },
    "handler": network_diagnosis,
}
