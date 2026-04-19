"""SSH tunnel support for database connections."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlit.domains.connections.domain.config import ConnectionConfig


class ChainedTunnel:
    """Nested SSHTunnelForwarder pair for ProxyJump."""

    def __init__(self, outer: Any, inner: Any) -> None:
        self._outer = outer
        self._inner = inner

    @property
    def local_bind_port(self) -> int:
        return int(self._inner.local_bind_port)

    def stop(self) -> None:
        inner_exc = None
        try:
            self._inner.stop()
        except Exception as e:
            inner_exc = e
        try:
            self._outer.stop()
        except Exception:
            pass  # Don't mask inner exception
        if inner_exc:
            raise inner_exc


def ensure_ssh_tunnel_available() -> None:
    """Ensure SSH tunnel dependencies are installed."""
    try:
        import sshtunnel  # noqa: F401
    except Exception as e:
        from sqlit.domains.connections.providers.exceptions import MissingDriverError

        raise MissingDriverError(
            "SSH tunnel",
            "ssh",
            "sshtunnel",
            module_name="sshtunnel",
            import_error=str(e),
        ) from e


def create_ssh_tunnel(config: ConnectionConfig) -> tuple[Any, str, int]:
    """Create an SSH tunnel for the connection if SSH is enabled.

    Returns:
        Tuple of (tunnel_object, local_host, local_port) if SSH enabled,
        or (None, original_server, original_port) if SSH not enabled.
    """
    endpoint = config.tcp_endpoint
    if endpoint is None:
        return None, "", 0
    if not config.tunnel or not config.tunnel.enabled:
        port = int(endpoint.port) if endpoint.port else 0
        return None, endpoint.host, port

    ensure_ssh_tunnel_available()

    if config.tunnel.source == "config":
        return _create_from_alias(config, endpoint)
    return _create_from_manual(config, endpoint)


def _create_from_manual(config: ConnectionConfig, endpoint: Any) -> tuple[Any, str, int]:
    """Create SSH tunnel from manual configuration."""
    from sshtunnel import SSHTunnelForwarder

    remote_host = endpoint.host
    remote_port = int(endpoint.port) if endpoint.port else 0

    ssh_host = config.tunnel.host  # type: ignore[union-attr]
    ssh_port = int(config.tunnel.port) if config.tunnel.port else 22  # type: ignore[union-attr]
    ssh_username = config.tunnel.username  # type: ignore[union-attr]

    ssh_kwargs: dict[str, Any] = {
        "ssh_username": ssh_username,
    }

    if config.tunnel.auth_type == "key":  # type: ignore[union-attr]
        key_path = os.path.expanduser(config.tunnel.key_path)  # type: ignore[union-attr]
        if Path(key_path).exists():
            ssh_kwargs["ssh_pkey"] = key_path
        else:
            raise ValueError(f"SSH key file not found: {key_path}")
    else:
        ssh_kwargs["ssh_password"] = config.tunnel.password  # type: ignore[union-attr]

    tunnel = SSHTunnelForwarder(
        (ssh_host, ssh_port),
        remote_bind_address=(remote_host, remote_port),
        **ssh_kwargs,
    )
    tunnel.start()

    return tunnel, "127.0.0.1", tunnel.local_bind_port


def _create_from_alias(config: ConnectionConfig, endpoint: Any) -> tuple[Any, str, int]:
    """Create SSH tunnel from ~/.ssh/config alias.

    NOTE: Only single-hop ProxyJump supported. Nested ProxyJump on the jump host
    is ignored. ProxyJump must be a bare alias (user@host:port syntax unsupported).
    """
    from sshtunnel import SSHTunnelForwarder

    from sqlit.domains.connections.app import ssh_config as ssh_cfg

    target = ssh_cfg.resolve(config.tunnel.config_alias)  # type: ignore[union-attr]
    remote = (endpoint.host, int(endpoint.port) if endpoint.port else 0)

    if target.proxyjump:
        # Single hop only — jump.proxyjump is not consulted
        jump = ssh_cfg.resolve(target.proxyjump)
        outer = SSHTunnelForwarder(
            (jump.hostname, jump.port),
            ssh_username=jump.user,
            ssh_pkey=jump.identityfile,
            remote_bind_address=(target.hostname, target.port),
        )
        outer.start()
        try:
            inner = SSHTunnelForwarder(
                ("127.0.0.1", outer.local_bind_port),
                ssh_username=target.user,
                ssh_pkey=target.identityfile,
                remote_bind_address=remote,
            )
            inner.start()
        except Exception:
            outer.stop()
            raise
        chain = ChainedTunnel(outer, inner)
        return chain, "127.0.0.1", chain.local_bind_port

    tunnel = SSHTunnelForwarder(
        (target.hostname, target.port),
        ssh_username=target.user,
        ssh_pkey=target.identityfile,
        remote_bind_address=remote,
    )
    tunnel.start()
    return tunnel, "127.0.0.1", tunnel.local_bind_port


def create_noop_tunnel(config: ConnectionConfig) -> tuple[Any, str, int]:
    """Return the original endpoint without creating a tunnel."""
    endpoint = config.tcp_endpoint
    if endpoint is None:
        return None, "", 0
    port = int(endpoint.port) if endpoint.port else 0
    return None, endpoint.host, port
