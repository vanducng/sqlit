"""SSH config discovery - parse ~/.ssh/config and expose aliases."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AliasInfo:
    """Resolved SSH alias information."""

    name: str
    hostname: str
    user: str | None
    port: int
    identityfile: str | None
    proxyjump: str | None


class SSHAliasNotFoundError(Exception):
    """Alias not present in ~/.ssh/config."""


def _has_wildcard(host: str) -> bool:
    """Check if host contains wildcard characters."""
    return any(c in host for c in ("*", "?", "!"))


def _to_alias_info(name: str, lookup: dict[str, Any]) -> AliasInfo:
    """Convert paramiko lookup dict to AliasInfo."""
    hostname = lookup.get("hostname", name)
    user = lookup.get("user")
    port_str = lookup.get("port", "22")
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        port = 22
    identityfiles = lookup.get("identityfile", [])
    identityfile = os.path.expanduser(identityfiles[0]) if identityfiles else None
    proxyjump = lookup.get("proxyjump")
    return AliasInfo(name=name, hostname=hostname, user=user, port=port, identityfile=identityfile, proxyjump=proxyjump)


def list_aliases(config_path: str | Path = "~/.ssh/config") -> list[AliasInfo]:
    """Top-level Host entries (excl. wildcards * ? !) with resolved fields.

    Returns [] if config file missing OR if paramiko not installed (ssh extra absent).
    """
    path = Path(os.path.expanduser(str(config_path)))
    if not path.exists():
        return []

    try:
        import paramiko
    except ImportError:
        return []

    try:
        config = paramiko.SSHConfig.from_path(str(path))
    except Exception:
        return []

    aliases: list[AliasInfo] = []
    for hostname in config.get_hostnames():
        if _has_wildcard(hostname):
            continue
        aliases.append(_to_alias_info(hostname, config.lookup(hostname)))
    return aliases


def resolve(alias: str, config_path: str | Path = "~/.ssh/config") -> AliasInfo:
    """Resolve one alias.

    Raises:
        SSHAliasNotFoundError — alias absent.
        FileNotFoundError     — config missing.
        MissingDriverError    — paramiko not installed.
    """
    path = Path(os.path.expanduser(str(config_path)))
    if not path.exists():
        raise FileNotFoundError(f"SSH config file not found: {path}")

    try:
        import paramiko
    except ImportError as e:
        from sqlit.domains.connections.providers.exceptions import MissingDriverError

        raise MissingDriverError(
            "SSH config discovery",
            "ssh",
            "paramiko",
            module_name="paramiko",
            import_error=str(e),
        ) from e

    config = paramiko.SSHConfig.from_path(str(path))

    hostnames = config.get_hostnames()
    if alias not in hostnames:
        raise SSHAliasNotFoundError(f"Alias '{alias}' not found in {path}")

    return _to_alias_info(alias, config.lookup(alias))
