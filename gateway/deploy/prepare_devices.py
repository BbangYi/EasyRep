"""One-time Pi provisioning. Secrets stay outside the release and command arguments."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import tomllib


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout.strip()


def private(path, text, uid=0, gid=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        os.fchown(f.fileno(), uid, gid)
        f.write(text)


def mqtt_acl(config):
    """Render only; this does not install ACLs or enable firmware request outputs."""
    bridge = config.get("r15_bridge", {})
    central = bridge.get("central_cage_id") if bridge.get("enabled") is True else None
    if bridge.get("enabled") is True and central not in {c["id"] for c in config["cages"]}:
        raise ValueError("R15 ACL requires an explicit configured central_cage_id")
    lines = ["user habitat-gateway", f"topic readwrite habitat/v1/{config['site_id']}/#", ""]
    for cage in config["cages"]:
        base = f"habitat/v1/{config['site_id']}/cages/{cage['id']}/nodes/{cage['node_id']}"
        lines += [f"user {cage['node_id']}", f"topic write {base}/telemetry", f"topic write {base}/status"]
        if cage["id"] == central:
            lines += [f"topic write {base}/r15/hello", f"topic write {base}/r15/ack",
                      f"topic read {base}/r15/command/+"]
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", required=True)
    parser.add_argument("--broker-ip", required=True, type=ipaddress.ip_address)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("run with sudo")
    user = pwd.getpwnam(args.user)
    home = Path(user.pw_dir)
    etc = Path("/etc/habitat-gateway")
    if (etc / "devices-provisioned.json").exists():
        raise SystemExit("already provisioned; existing credentials were preserved")
    if (etc / "gateway.env").exists() or Path("/etc/mosquitto/conf.d/habitat.conf").exists():
        raise SystemExit("existing configuration needs review; refusing to overwrite")
    config = tomllib.loads(args.profile.read_text())
    acl = mqtt_acl(config)
    from install import read_environment
    env = read_environment(home / ".config/habitatos/gateway.env")
    env.update(read_environment(home / ".config/habitatos/gpu.env"))
    if not env.get("HABITAT_GPU_TOKEN") or not env.get("HABITAT_CLOUD_TOKEN"):
        raise SystemExit("provision GPU and SaaS credentials first")
    env["HABITAT_API_TOKEN"] = secrets.token_urlsafe(32)
    env["HABITAT_MQTT_PASSWORD"] = secrets.token_urlsafe(32)
    etc.mkdir(mode=0o755, exist_ok=True)
    certificates = Path("/etc/mosquitto/certs")
    certificates.mkdir(parents=True, exist_ok=True)
    crt, key = certificates / "habitat.crt", certificates / "habitat.key"
    if crt.exists() or key.exists():
        raise SystemExit("existing broker certificate needs review")
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
        "-keyout", str(key), "-out", str(crt), "-subj", "/CN=habitat-pi",
        "-addext", f"subjectAltName=IP:127.0.0.1,IP:{args.broker_ip},DNS:habitat-pi.local")
    broker = pwd.getpwnam("mosquitto")
    key.chmod(0o640); os.chown(key, 0, broker.pw_gid); crt.chmod(0o644)
    ssid = psk = ""
    for row in run("nmcli", "-t", "-f", "UUID,TYPE", "connection", "show", "--active").splitlines():
        identity, _, kind = row.partition(":")
        if kind == "802-11-wireless":
            ssid = run("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", identity)
            psk = run("nmcli", "--show-secrets", "-g", "802-11-wireless-security.psk", "connection", "show", identity)
            break
    credentials = {"habitat-gateway": env["HABITAT_MQTT_PASSWORD"]}
    nodes = home / ".config/habitatos/nodes"
    nodes.mkdir(mode=0o700, exist_ok=True)
    os.chown(nodes, user.pw_uid, user.pw_gid)
    for cage in config["cages"]:
        node_id = cage["node_id"]
        credentials[node_id] = secrets.token_urlsafe(32)
        topic = f"habitat/v1/{config['site_id']}/cages/{cage['id']}/nodes/{node_id}"
        directory = nodes / node_id
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chown(directory, user.pw_uid, user.pw_gid)
        values = {"WIFI_SSID": ssid, "WIFI_PASSWORD": psk, "MQTT_HOST": str(args.broker_ip),
                  "MQTT_USER": node_id, "MQTT_PASSWORD": credentials[node_id], "TOPIC_BASE": topic}
        header = "#pragma once\n" + "".join(f"const char* {k} = {json.dumps(v, ensure_ascii=False)};\n" for k,v in values.items())
        header += 'const char* MQTT_CA = R"CERT(' + crt.read_text() + ')CERT";\n'
        private(directory / "config.h", header, user.pw_uid, user.pw_gid)
    password_file = Path("/etc/mosquitto/habitat.passwd")
    private(password_file, "".join(f"{k}:{v}\n" for k,v in credentials.items()))
    run("mosquitto_passwd", "-U", str(password_file))
    password_file.chmod(0o640); os.chown(password_file, 0, broker.pw_gid)
    acl_path = Path("/etc/mosquitto/habitat.acl")
    acl_path.write_text(acl); acl_path.chmod(0o644)
    Path("/etc/mosquitto/conf.d/habitat.conf").write_text(
        "listener 8883\nallow_anonymous false\ncertfile /etc/mosquitto/certs/habitat.crt\n"
        "keyfile /etc/mosquitto/certs/habitat.key\npassword_file /etc/mosquitto/habitat.passwd\n"
        "acl_file /etc/mosquitto/habitat.acl\n")
    private(etc / "gateway.env", "".join(f"{k}={v}\n" for k,v in sorted(env.items())))
    run("systemctl", "restart", "mosquitto")
    run("systemctl", "enable", "mosquitto")
    receipt = {"node_count": len(config["cages"]), "wifi_configured": bool(ssid and psk),
               "mqtt_tls_port": 8883, "hardware_outputs_enabled": False}
    private(etc / "devices-provisioned.json", json.dumps(receipt))
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
