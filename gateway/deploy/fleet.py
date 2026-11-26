"""Deploy one checked release to explicitly listed Pis, sequentially over SSH."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tomllib


def load_inventory(path):
    records = json.loads(path.read_text())
    if not isinstance(records, list) or not records:
        raise ValueError("inventory must be a nonempty list")
    sites, gateways, hosts = set(), set(), set()
    for item in records:
        if not isinstance(item, dict) or not {"host", "site_id", "gateway_id", "config"} <= item.keys():
            raise ValueError("each target needs host, site_id, gateway_id and config")
        if not item.keys() <= {"host", "site_id", "gateway_id", "config", "port", "identity_file"}:
            raise ValueError("unknown inventory field")
        if not re.fullmatch(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*", item["host"]):
            raise ValueError("host must be hostname or user@hostname (no shell syntax)")
        for field in ("site_id", "gateway_id"):
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item[field]):
                raise ValueError(f"invalid {field}")
        port = item.get("port", 22)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("invalid SSH port")
        host_key = (item["host"].split("@")[-1], port)
        if item["site_id"] in sites or item["gateway_id"] in gateways or host_key in hosts:
            raise ValueError("each deployment target must have a unique site, gateway and host")
        sites.add(item["site_id"])
        gateways.add(item["gateway_id"])
        hosts.add(host_key)
        item["config"] = (path.parent / item["config"]).resolve()
        config = tomllib.loads(item["config"].read_text())
        if any(config[field] != item[field] for field in ("site_id", "gateway_id")):
            raise ValueError("inventory/config identity mismatch")
        if "identity_file" in item:
            item["identity_file"] = (path.parent / item["identity_file"]).resolve()
            if not item["identity_file"].is_file():
                raise ValueError("SSH identity_file does not exist")
    return records


def ssh_options(target, scp=False):
    options = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "ConnectTimeout=10",
               "-P" if scp else "-p", str(target.get("port", 22))]
    if "identity_file" in target:
        options.extend(["-i", str(target["identity_file"])])
    return options


def remote(target, *args):
    return subprocess.run(["ssh", *ssh_options(target), target["host"], shlex.join(args)],
                          check=True, text=True, capture_output=True)


def deploy(target, archive, installer):
    directory = remote(target, "mktemp", "-d", "/tmp/habitat-deploy.XXXXXXXX").stdout.strip()
    if not re.fullmatch(r"/tmp/habitat-deploy\.[A-Za-z0-9]{8}", directory):
        raise ValueError("unexpected remote temporary directory")
    # Only an explicitly supplied host is contacted. Host keys must already be trusted.
    for source, name in ((archive, "release.tar.gz"), (installer, "install.py"), (target["config"], "gateway.toml")):
        subprocess.run(["scp", *ssh_options(target, scp=True), str(source),
                        f"{target['host']}:{directory}/{name}"], check=True)
    expected = hashlib.sha256(archive.read_bytes()).hexdigest()
    actual = remote(target, "sha256sum", f"{directory}/release.tar.gz").stdout.split()[0]
    if expected != actual:
        raise ValueError("uploaded archive checksum mismatch")
    result = remote(target, "sudo", "-n", "python3", f"{directory}/install.py", "--archive",
                    f"{directory}/release.tar.gz", "--config", f"{directory}/gateway.toml")
    print(result.stdout, end="")
    # Retain failed uploads for diagnosis; only remove the known files after success.
    remote(target, "python3", "-c",
           "from pathlib import Path; p=Path(" + repr(directory) + "); "
           "[(p/n).unlink() for n in ('release.tar.gz','install.py','gateway.toml')]; p.rmdir()")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--site-id", help="Deploy only this site (start with a single canary Pi)")
    parser.add_argument("--apply", action="store_true", help="Without this option, validate and show targets only")
    args = parser.parse_args()
    archive = args.archive.resolve()
    if not archive.is_file():
        parser.error("release archive does not exist")
    targets = load_inventory(args.inventory.resolve())
    if args.site_id:
        targets = [target for target in targets if target["site_id"] == args.site_id]
        if not targets:
            parser.error("site_id not found in inventory")
    for target in targets:
        print(json.dumps({"host": target["host"], "site_id": target["site_id"],
                          "gateway_id": target["gateway_id"], "apply": args.apply}), flush=True)
        if args.apply:
            try:
                deploy(target, archive, Path(__file__).with_name("install.py").resolve())
            except subprocess.CalledProcessError as error:
                # These commands never print credentials; expose useful SSH/systemd diagnostics.
                raise SystemExit(error.stderr or str(error)) from error


if __name__ == "__main__":
    main()
