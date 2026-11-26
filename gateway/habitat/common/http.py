import ipaddress
import os


def validate_service_url(url, label, *, root_only=False):
    if url.username or url.password or url.query or url.fragment:
        raise ValueError(f"{label} must not contain credentials, query or fragment")
    loopback = url.host == "localhost"
    try:
        loopback = loopback or ipaddress.ip_address(url.host.strip("[]")).is_loopback
    except ValueError:
        pass
    if url.scheme != "https" and not loopback:
        raise ValueError(f"{label} requires HTTPS except for loopback development")
    if root_only and url.path not in (None, "", "/"):
        raise ValueError(f"{label} must be an origin URL without an API path")
    return url


def bearer_token(name, *, usage):
    token = os.environ.get(name, "")
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise ValueError(f"{usage} requires {name} (32+ ASCII characters, no whitespace)")
    return token
