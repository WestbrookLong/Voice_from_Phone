#!/usr/bin/env python3
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CERT_DIR = ROOT / "certs"
CA_KEY = CERT_DIR / "local-ca.key"
CA_CERT = CERT_DIR / "local-ca.crt"
SERVER_KEY = CERT_DIR / "server.key"
SERVER_CSR = CERT_DIR / "server.csr"
SERVER_CERT = CERT_DIR / "server.crt"
OPENSSL_CONFIG = CERT_DIR / "server-openssl.cnf"


def get_lan_ip() -> str:
    return get_lan_ips()[0]


def get_lan_ips() -> list[str]:
    interface_ips: list[tuple[str, str]] = []
    current_interface = ""
    try:
        output = subprocess.check_output(["ifconfig"], text=True)
    except (OSError, subprocess.CalledProcessError):
        output = ""

    for line in output.splitlines():
        if line and not line.startswith(("\t", " ")):
            current_interface = line.split(":", 1)[0]
            continue
        match = re.search(r"\binet\s+(\d+\.\d+\.\d+\.\d+)\b", line)
        if not match:
            continue
        ip = match.group(1)
        if ip.startswith("127.") or ip.startswith("169.254."):
            continue
        interface_ips.append((current_interface, ip))

    preferred_prefixes = ("en", "bridge", "ap")
    preferred = [ip for name, ip in interface_ips if name.startswith(preferred_prefixes)]
    fallback = [ip for name, ip in interface_ips if not name.startswith(("lo", "utun", "gif", "stf"))]
    all_ips = preferred + fallback + [ip for _, ip in interface_ips]

    unique: list[str] = []
    for ip in all_ips:
        if ip not in unique:
            unique.append(ip)

    if unique:
        return unique

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return [s.getsockname()[0]]
    except OSError:
        return ["127.0.0.1"]


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True)
    except FileNotFoundError:
        raise SystemExit("openssl was not found. Install OpenSSL or ensure /usr/bin/openssl is available.")
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"openssl command failed: {' '.join(command)}\nexit code: {exc.returncode}")


def alt_name_lines(lan_ips: list[str]) -> list[str]:
    lines = [
        "DNS.1 = localhost",
        "IP.1 = 127.0.0.1",
    ]
    for index, ip in enumerate(lan_ips, start=2):
        lines.append(f"IP.{index} = {ip}")
    return lines


def write_server_config(lan_ips: list[str]) -> Path:
    config = f"""
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = Voice from Phone Local Server

[req_ext]
subjectAltName = @alt_names

[alt_names]
{os.linesep.join(alt_name_lines(lan_ips))}
""".strip()
    OPENSSL_CONFIG.write_text(config + "\n", encoding="utf-8")
    return OPENSSL_CONFIG


def ensure_ca() -> None:
    if CA_KEY.exists() and CA_CERT.exists():
        return
    run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-days",
            "3650",
            "-keyout",
            str(CA_KEY),
            "-out",
            str(CA_CERT),
            "-subj",
            "/CN=Voice from Phone Local CA",
            "-sha256",
        ]
    )


def create_server_certificate(lan_ips: list[str]) -> None:
    config = write_server_config(lan_ips)
    run(
        [
            "openssl",
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(SERVER_KEY),
            "-out",
            str(SERVER_CSR),
            "-config",
            str(config),
        ]
    )

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as ext:
        ext.write(
            "\n".join(
                [
                    "subjectAltName = @alt_names",
                    "basicConstraints = CA:FALSE",
                    "keyUsage = digitalSignature, keyEncipherment",
                    "extendedKeyUsage = serverAuth",
                    "",
                    "[alt_names]",
                    *alt_name_lines(lan_ips),
                    "",
                ]
            )
        )
        ext_path = Path(ext.name)

    try:
        run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                str(SERVER_CSR),
                "-CA",
                str(CA_CERT),
                "-CAkey",
                str(CA_KEY),
                "-CAcreateserial",
                "-out",
                str(SERVER_CERT),
                "-days",
                "825",
                "-sha256",
                "-extfile",
                str(ext_path),
            ]
        )
    finally:
        ext_path.unlink(missing_ok=True)


def lock_down_private_keys() -> None:
    for path in (CA_KEY, SERVER_KEY):
        if path.exists():
            os.chmod(path, 0o600)


def main() -> None:
    if shutil.which("openssl") is None:
        raise SystemExit("openssl was not found. macOS usually includes /usr/bin/openssl.")

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    lan_ips = get_lan_ips()
    ensure_ca()
    create_server_certificate(lan_ips)
    lock_down_private_keys()

    SERVER_CSR.unlink(missing_ok=True)

    print("HTTPS certificates are ready.")
    print(f"Preferred LAN IP: {lan_ips[0]}")
    print(f"IP addresses included in certificate: {', '.join(lan_ips)}")
    print(f"CA certificate for phones: {CA_CERT}")
    print(f"Server certificate: {SERVER_CERT}")
    print(f"Server private key: {SERVER_KEY}")
    print("")
    print("Start HTTPS server with:")
    print("  python3 server.py --https")


if __name__ == "__main__":
    main()
