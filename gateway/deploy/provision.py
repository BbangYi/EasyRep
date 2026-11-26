"""Create a store-specific config. No secrets, network access, or actuation."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
import tomllib


def toml_value(value):
    """Encode the scalar/inline inventory values used by gateway profiles."""
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(key) + " = " + toml_value(item)
                                for key, item in value.items()) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if value is None or not isinstance(value, (str, bool, int, float)):
        raise ValueError("unsupported value in gateway profile")
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def array_table(name, values):
    return "[[" + name + "]]\n" + "".join(
        json.dumps(key) + " = " + toml_value(value) + "\n"
        for key, value in values.items() if value is not None)


def add_cage(template, cage_id, node_id, template_cage_id):
    """Reuse explicit inventory, without policies, credentials or output activation."""
    from habitat_gateway.config import Settings
    current = tomllib.loads(template)
    Settings.model_validate(current)
    if any(cage["id"] == cage_id for cage in current["cages"]):
        raise ValueError("cage ID already exists; use bind-camera-pair for an existing cage")
    if any(cage["node_id"] == node_id for cage in current["cages"]):
        raise ValueError("node ID is already assigned to a cage")
    reference = next((cage for cage in current["cages"] if cage["id"] == template_cage_id), None)
    if reference is None:
        raise ValueError("unknown template cage")
    cage = deepcopy(reference)
    cage.update(id=cage_id, node_id=node_id, geometry_revision=1, placement_revision=1, policies=[])
    proposed = template.rstrip() + "\n\n" + array_table("cages", cage)
    Settings.model_validate(tomllib.loads(proposed))
    return proposed


def generate(template, site_id, gateway_id, transport="simulated", *, saas_url=None, gpu_url=None):
    for value in (site_id, gateway_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("IDs may contain only letters, numbers, underscores and hyphens")
    if transport not in ("simulated", "mqtt"):
        raise ValueError("invalid transport")
    prefix, separator, cages = template.partition("[[cages]]")
    if not separator:
        raise ValueError("template needs cage definitions")
    values = {"site_id": site_id, "gateway_id": gateway_id, "transport": transport,
              "database": "/var/lib/habitat-gateway/gateway.sqlite3"}
    for key, value in values.items():
        prefix, count = re.subn(rf'(?m)^{key}\s*=.*$', f'{key} = "{value}"', prefix)
        if count != 1:
            raise ValueError(f"template must define exactly one root {key}")
    result = prefix + separator + cages
    for section, key, value in (("cloud", "endpoint", saas_url), ("environment", "base_url", gpu_url)):
        if value is None:
            continue
        # Update only an existing, explicit device profile; never invent cage targets.
        match = re.search(rf"(?ms)^\[{section}\]\s*\n(.*?)(?=^\[|\Z)", result)
        if match is None:
            raise ValueError(f"template requires [{section}] for this URL")
        body, count = re.subn(rf"(?m)^{key}\s*=.*$", lambda _: f"{key} = {json.dumps(value)}", match[1])
        if count != 1:
            raise ValueError(f"template must define one {section}.{key}")
        result = result[:match.start(1)] + body + result[match.end(1):]
    if saas_url is not None or gpu_url is not None:
        from habitat_gateway.config import Settings
        Settings.model_validate(tomllib.loads(result))
    else:
        tomllib.loads(result)
    return result


def generate_heartbeat(template, cloud_defaults, site_id, gateway_id, cage_ids, endpoint):
    """Map a new registration to inactive inventory; never generate measurements."""
    if not cage_ids or len(cage_ids) > 64 or len(set(cage_ids)) != len(cage_ids):
        raise ValueError("provide 1 to 64 distinct cage IDs")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value) for value in cage_ids):
        raise ValueError("invalid cage ID")
    base = generate(template, site_id, gateway_id, transport="mqtt")
    prefix, _, cage = base.partition("[[cages]]")
    if "[[cages]]" in cage or "cloud" in tomllib.loads(base):
        raise ValueError("heartbeat template must contain one cage and no cloud settings")
    header, nested, children = cage.partition("[[cages.")
    if not nested:
        raise ValueError("heartbeat template needs sensor and actuator inventory")
    mapped = []
    for index, cage_id in enumerate(cage_ids, 1):
        mapped_header = header
        for key, value in (("id", cage_id), ("node_id", f"UNASSIGNED-{index:03d}")):
            mapped_header, count = re.subn(rf"(?m)^{key}\s*=.*$", f"{key} = {json.dumps(value)}", mapped_header)
            if count != 1:
                raise ValueError("invalid cage identity in heartbeat template")
        # Policies in the example are not operational defaults for a new store.
        inventory = re.split(r"(?m)^\[\[cages\.policies\]\]", children, maxsplit=1)[0]
        mapped.append("[[cages]]" + mapped_header + nested + inventory)
    cloud = tomllib.loads(cloud_defaults)["cloud"]
    cloud.update(enabled=True, endpoint=endpoint)
    section = "[cloud]\n" + "\n".join(f"{key} = {json.dumps(value, ensure_ascii=False)}" for key, value in cloud.items())
    result = ("# HEARTBEAT ONLY: expected inventory, no installed devices or live readings.\n"
              "# Configure real sensor/node mappings and safety limits before enabling device control.\n"
              + prefix + section + "\n\n" + "\n".join(mapped))
    tomllib.loads(result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate a per-store Pi configuration")
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--gateway-id", required=True)
    parser.add_argument("--transport", choices=["simulated", "mqtt"], default="simulated")
    parser.add_argument("--template", type=Path, default=Path("config/simulation.toml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--saas-url", help="SaaS sync endpoint for this store")
    parser.add_argument("--gpu-url", help="Separate GPU API origin for this store")
    args = parser.parse_args()
    result = generate(args.template.read_text(), args.site_id, args.gateway_id, args.transport,
                      saas_url=args.saas_url, gpu_url=args.gpu_url)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(result)
    print(f"Created {args.output}; review cage definitions and example thresholds before hardware use.")


if __name__ == "__main__":
    main()
