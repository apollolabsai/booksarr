import asyncio
import logging
import os
import shutil
import subprocess

logger = logging.getLogger("booksarr.vpn")

_openvpn_process: subprocess.Popen | None = None
_vpn_interface_ip: str | None = None

PIA_CA_CERT = """\
-----BEGIN CERTIFICATE-----
MIIFqzCCBJOgAwIBAgIJAKZ7D5Yv87qDMA0GCSqGSIb3DQEBDQUAMIHoMQswCQYD
VQQGEwJVUzELMAkGA1UECBMCQ0ExEzARBgNVBAcTCkxvc0FuZ2VsZXMxIDAeBgNV
BAoTF1ByaXZhdGUgSW50ZXJuZXQgQWNjZXNzMSAwHgYDVQQLExdQcml2YXRlIElu
dGVybmV0IEFjY2VzczEgMB4GA1UEAxMXUHJpdmF0ZSBJbnRlcm5ldCBBY2Nlc3Mx
IDAeBgNVBCkTF1ByaXZhdGUgSW50ZXJuZXQgQWNjZXNzMS8wLQYJKoZIhvcNAQkB
FiBzZWN1cmVAcHJpdmF0ZWludGVybmV0YWNjZXNzLmNvbTAeFw0xNDA0MTcxNzM1
MThaFw0zNDA0MTIxNzM1MThaMIHoMQswCQYDVQQGEwJVUzELMAkGA1UECBMCQ0Ex
EzARBgNVBAcTCkxvc0FuZ2VsZXMxIDAeBgNVBAoTF1ByaXZhdGUgSW50ZXJuZXQg
QWNjZXNzMSAwHgYDVQQLExdQcml2YXRlIEludGVybmV0IEFjY2VzczEgMB4GA1UE
AxMXUHJpdmF0ZSBJbnRlcm5ldCBBY2Nlc3MxIDAeBgNVBCkTF1ByaXZhdGUgSW50
ZXJuZXQgQWNjZXNzMS8wLQYJKoZIhvcNAQkBFiBzZWN1cmVAcHJpdmF0ZWludGVy
bmV0YWNjZXNzLmNvbTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAPXD
L1L9tX6DGf36liA7UBTy5I869z0UVo3lImfOs/GSiFKPtInlesP65577nd7UNzzX
lH/P/CnFPdBWlLp5ze3HRBCc/Avgr5CdMRkEsySL5GHBZsx6w2cayQ2EcRhVTwWp
cdldeNO+pPr9rIgPrtXqT4SWViTQRBeGM8CDxAyTopTsobjSiYZCF9Ta1gunl0G/
8Vfp+SXfYCC+ZzWvP+L1pFhPRqzQQ8k+wMZIovObK1s+nlwPaLyayzw9a8sUnvWB
/5rGPdIYnQWPgoNlLN9HpSmsAcw2z8DXI9pIxbr74cb3/HSfuYGOLkRqrOk6h4RC
OfuWoTrZup1uEOn+fw8CAwEAAaOCAVQwggFQMB0GA1UdDgQWBBQv63nQ/pJAt5tL
y8VJcbHe22ZOsjCCAR8GA1UdIwSCARYwggESgBQv63nQ/pJAt5tLy8VJcbHe22ZO
sqGB7qSB6zCB6DELMAkGA1UEBhMCVVMxCzAJBgNVBAgTAkNBMRMwEQYDVQQHEwpM
b3NBbmdlbGVzMSAwHgYDVQQKExdQcml2YXRlIEludGVybmV0IEFjY2VzczEgMB4G
A1UECxMXUHJpdmF0ZSBJbnRlcm5ldCBBY2Nlc3MxIDAeBgNVBAMTF1ByaXZhdGUg
SW50ZXJuZXQgQWNjZXNzMSAwHgYDVQQpExdQcml2YXRlIEludGVybmV0IEFjY2Vz
czEvMC0GCSqGSIb3DQEJARYgc2VjdXJlQHByaXZhdGVpbnRlcm5ldGFjY2Vzcy5j
b22CCQCmew+WL/O6gzAMBgNVHRMEBTADAQH/MA0GCSqGSIb3DQEBDQUAA4IBAQAn
a5PgrtxfwTumD4+3/SYvwoD66cB8IcK//h1mCzAduU8KgUXocLx7QgJWo9lnZ8xU
ryXvWab2usg4fqk7FPi00bED4f4qVQFVfGfPZIH9QQ7/48bPM9RyfzImZWUCenK3
7pdw4Bvgoys2rHLHbGen7f28knT2j/cbMxd78tQc20TIObGjo8+ISTRclSTRBtyC
GohseKYpTS9himFERpUgNtefvYHbn70mIOzfOJFTVqfrptf9jXa9N8Mpy3ayfodz
1wiqdteqFXkTYoSDctgKMiZ6GdocK9nMroQipIQtpnwd4yBDWIyC6Bvlkrq5TQUt
YDQ8z9v+DMO6iwyIDRiU
-----END CERTIFICATE-----
"""

PIA_REGIONS: dict[str, str] = {
    "Netherlands": "nl-amsterdam.privacy.network",
    "US East": "us3.privacy.network",
    "US West": "us-west.privacy.network",
    "US California": "us-california.privacy.network",
    "US New York": "us-newyorkcity.privacy.network",
    "US Chicago": "us-chicago.privacy.network",
    "US Florida": "us-florida.privacy.network",
    "US Texas": "us-texas.privacy.network",
    "US Seattle": "us-seattle.privacy.network",
    "US Denver": "us-denver.privacy.network",
    "Canada Montreal": "ca-montreal.privacy.network",
    "Canada Toronto": "ca-toronto.privacy.network",
    "Canada Vancouver": "ca-vancouver.privacy.network",
    "UK London": "uk-london.privacy.network",
    "UK Manchester": "uk-manchester.privacy.network",
    "Germany Berlin": "de-berlin.privacy.network",
    "Germany Frankfurt": "de-frankfurt.privacy.network",
    "France": "france.privacy.network",
    "Switzerland": "swiss.privacy.network",
    "Sweden": "sweden.privacy.network",
    "Romania": "ro.privacy.network",
    "Australia Sydney": "au-sydney.privacy.network",
    "Australia Melbourne": "aus-melbourne.privacy.network",
    "Japan": "japan.privacy.network",
    "Ireland": "ireland.privacy.network",
    "Israel": "israel.privacy.network",
    "Norway": "no.privacy.network",
    "Spain": "spain.privacy.network",
    "Italy": "italy.privacy.network",
    "Brazil": "br.privacy.network",
    "Mexico": "mexico.privacy.network",
    "Singapore": "sg.privacy.network",
}

_CONFIG_DIR = "/config/vpn"


def _write_openvpn_config(region_host: str, username: str, password: str) -> str:
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    creds_path = os.path.join(_CONFIG_DIR, "pia_creds.txt")
    with open(creds_path, "w") as f:
        f.write(f"{username}\n{password}\n")
    os.chmod(creds_path, 0o600)

    ca_path = os.path.join(_CONFIG_DIR, "ca.crt")
    with open(ca_path, "w") as f:
        f.write(PIA_CA_CERT)

    config_path = os.path.join(_CONFIG_DIR, "pia.ovpn")
    config = f"""\
client
dev tun
proto udp
remote {region_host} 1198
resolv-retry infinite
nobind
persist-key
persist-tun
cipher aes-128-cbc
auth sha1
tls-client
remote-cert-tls server
auth-user-pass {creds_path}
ca {ca_path}
compress
verb 2
reneg-sec 0
disable-occ
route-nopull
pull-filter ignore "redirect-gateway"
pull-filter ignore "route-ipv6"
pull-filter ignore "dhcp-option"
script-security 2
"""
    with open(config_path, "w") as f:
        f.write(config)
    return config_path


def _get_tun_ip() -> str | None:
    try:
        output = subprocess.check_output(
            ["ip", "-4", "addr", "show", "dev", "tun0"],
            text=True,
            timeout=5,
        )
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                return line.split()[1].split("/")[0]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _setup_policy_routing(tun_ip: str):
    try:
        output = subprocess.check_output(
            ["ip", "route", "show", "dev", "tun0"],
            text=True,
            timeout=5,
        )
        gateway = None
        use_direct_tun_default = False
        for line in output.splitlines():
            parts = line.split()
            if "via" in parts:
                gateway = parts[parts.index("via") + 1]
                break

        if not gateway:
            # TUN devices commonly expose only a connected subnet route like:
            # `10.243.0.0/16 proto kernel scope link src 10.243.0.194`
            # There is no next-hop gateway in that case, so the correct policy
            # route is `default dev tun0`, not `default via <subnet>`.
            use_direct_tun_default = True

        subprocess.run(
            ["ip", "rule", "del", "from", tun_ip, "table", "100"],
            check=False,
            timeout=5,
        )
        subprocess.run(
            ["ip", "route", "flush", "table", "100"],
            check=False,
            timeout=5,
        )

        subprocess.run(
            ["ip", "rule", "add", "from", tun_ip, "table", "100"],
            check=True,
            timeout=5,
        )

        if gateway and not use_direct_tun_default:
            subprocess.run(
                ["ip", "route", "add", "default", "via", gateway, "dev", "tun0", "table", "100"],
                check=True,
                timeout=5,
            )
            logger.info("VPN policy routing configured: %s via %s on table 100", tun_ip, gateway)
        else:
            subprocess.run(
                ["ip", "route", "add", "default", "dev", "tun0", "table", "100"],
                check=True,
                timeout=5,
            )
            logger.info("VPN policy routing configured: %s via tun0 on table 100", tun_ip)
    except Exception as exc:
        logger.warning("Failed to set up VPN policy routing: %s", exc)


def _cleanup_policy_routing():
    try:
        subprocess.run(["ip", "rule", "del", "table", "100"], check=False, timeout=5)
        subprocess.run(["ip", "route", "flush", "table", "100"], check=False, timeout=5)
    except Exception:
        pass


def _collect_openvpn_output(*, stop_process: bool = False) -> str:
    if not _openvpn_process:
        return ""

    try:
        if stop_process and _openvpn_process.poll() is None:
            _openvpn_process.terminate()
        stdout, _ = _openvpn_process.communicate(timeout=5)
        if isinstance(stdout, bytes):
            return stdout.decode(errors="replace")
        return stdout or ""
    except subprocess.TimeoutExpired:
        try:
            _openvpn_process.kill()
            stdout, _ = _openvpn_process.communicate(timeout=5)
            if isinstance(stdout, bytes):
                return stdout.decode(errors="replace")
            return stdout or ""
        except Exception:
            return ""
    except Exception:
        return ""


async def start_vpn(username: str, password: str, region: str) -> str:
    global _openvpn_process, _vpn_interface_ip

    if _openvpn_process and _openvpn_process.poll() is None:
        logger.info("VPN already running (pid %d), stopping first", _openvpn_process.pid)
        await stop_vpn()

    region_host = PIA_REGIONS.get(region)
    if not region_host:
        raise RuntimeError(f"Unknown PIA region: {region}")

    if not shutil.which("openvpn"):
        raise RuntimeError("openvpn is not installed in the container")
    if not os.path.exists("/dev/net/tun"):
        raise RuntimeError(
            "VPN requires /dev/net/tun inside the container. "
            "On the host, enable the TUN device and mount it into Docker with NET_ADMIN."
        )

    config_path = _write_openvpn_config(region_host, username, password)
    logger.info("Starting OpenVPN: region=%s host=%s", region, region_host)

    _openvpn_process = subprocess.Popen(
        ["openvpn", "--config", config_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    for attempt in range(30):
        await asyncio.sleep(1)
        if _openvpn_process.poll() is not None:
            stdout = _collect_openvpn_output()
            _openvpn_process = None
            if "AUTH_FAILED" in stdout:
                raise RuntimeError("VPN authentication failed. Check your PIA username and password.")
            if "Cannot open TUN/TAP dev /dev/net/tun" in stdout:
                raise RuntimeError(
                    "VPN tunnel device /dev/net/tun is unavailable inside the container. "
                    "The remote host must expose /dev/net/tun to Docker and allow NET_ADMIN."
                )
            raise RuntimeError(f"OpenVPN exited unexpectedly: {stdout[-500:]}")
        tun_ip = _get_tun_ip()
        if tun_ip:
            _vpn_interface_ip = tun_ip
            _setup_policy_routing(tun_ip)
            logger.info("VPN connected: tun0 IP = %s (took %ds)", tun_ip, attempt + 1)
            return tun_ip

    openvpn_output = _collect_openvpn_output(stop_process=True)
    _openvpn_process = None
    _cleanup_policy_routing()
    _vpn_interface_ip = None
    if openvpn_output:
        logger.warning("OpenVPN did not bring up tun0 within 30s. Recent output: %s", openvpn_output[-1000:].strip())
    if openvpn_output:
        raise RuntimeError(f"VPN connection timed out waiting for tun0 interface (30s). OpenVPN output: {openvpn_output[-500:].strip()}")
    raise RuntimeError("VPN connection timed out waiting for tun0 interface (30s)")


async def stop_vpn():
    global _openvpn_process, _vpn_interface_ip
    _cleanup_policy_routing()
    _vpn_interface_ip = None
    if _openvpn_process:
        logger.info("Stopping OpenVPN (pid %d)", _openvpn_process.pid)
        _openvpn_process.terminate()
        try:
            _openvpn_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _openvpn_process.kill()
            _openvpn_process.wait(timeout=5)
        _openvpn_process = None
        logger.info("OpenVPN stopped")


def get_vpn_status() -> dict:
    running = _openvpn_process is not None and _openvpn_process.poll() is None
    tun_ip = _get_tun_ip() if running else None
    return {
        "running": running,
        "tun_ip": tun_ip,
    }


def get_vpn_interface_ip() -> str | None:
    if _openvpn_process and _openvpn_process.poll() is None:
        return _vpn_interface_ip
    return None
