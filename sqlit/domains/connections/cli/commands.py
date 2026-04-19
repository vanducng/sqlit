"""CLI command handlers for sqlit."""

from __future__ import annotations

import sys
from typing import Any

from sqlit.domains.connections.app.credentials import (
    ALLOW_PLAINTEXT_CREDENTIALS_SETTING,
    CredentialsPersistError,
    build_credentials_service,
    is_keyring_usable,
)
from sqlit.domains.connections.domain.config import (
    AUTH_TYPE_LABELS,
    AuthType,
    ConnectionConfig,
    DatabaseType,
    get_database_type_labels,
)
from sqlit.domains.connections.providers.catalog import get_provider_schema
from sqlit.shared.app.runtime import RuntimeConfig
from sqlit.shared.app.services import AppServices, build_app_services

from .helpers import build_connection_config_from_args


def _find_connection_index(connections: list[ConnectionConfig], name: str) -> int | None:
    for idx, conn in enumerate(connections):
        if conn.name == name:
            return idx
    return None


def _ensure_password_storage(
    services: AppServices,
    config: ConnectionConfig,
) -> None:
    has_db_password = bool(config.tcp_endpoint and config.tcp_endpoint.password)
    has_ssh_password = bool(config.tunnel and config.tunnel.password)
    if (has_db_password or has_ssh_password) and not is_keyring_usable():
        if not _maybe_prompt_plaintext_credentials(services):
            _clear_passwords_if_not_persisted(config)


def _maybe_prompt_plaintext_credentials(services: AppServices) -> bool:
    """Ensure plaintext credential storage preference is set when keyring isn't usable.

    Returns True if plaintext storage is allowed; False otherwise.
    """
    if is_keyring_usable():
        return False

    settings = services.settings_store.load_all()
    existing = settings.get(ALLOW_PLAINTEXT_CREDENTIALS_SETTING)
    if isinstance(existing, bool):
        if existing:
            services.credentials_service = build_credentials_service(services.settings_store)
            if hasattr(services.connection_store, "set_credentials_service"):
                services.connection_store.set_credentials_service(services.credentials_service)
        return existing

    if not sys.stdin.isatty():
        return False

    answer = input("Keyring isn't available. Save passwords as plaintext in the sqlit config directory? [y/N]: ").strip().lower()
    allow = answer in {"y", "yes"}
    settings[ALLOW_PLAINTEXT_CREDENTIALS_SETTING] = allow
    services.settings_store.save_all(settings)
    if allow:
        services.credentials_service = build_credentials_service(services.settings_store)
        if hasattr(services.connection_store, "set_credentials_service"):
            services.connection_store.set_credentials_service(services.credentials_service)
    return allow


def _clear_passwords_if_not_persisted(config: ConnectionConfig) -> None:
    endpoint = config.tcp_endpoint
    if endpoint:
        endpoint.password = ""
    if config.tunnel:
        config.tunnel.password = ""


def _save_connections(services: AppServices, connections: list[ConnectionConfig]) -> None:
    try:
        services.connection_store.save_all(connections)
    except CredentialsPersistError as exc:
        print(f"Warning: {exc}", file=sys.stderr)


def _summarize_connection(conn: ConnectionConfig, services: AppServices) -> dict[str, Any]:
    """Derive human-readable + structured summary fields for one connection."""
    labels = get_database_type_labels()
    db_type_label = labels.get(conn.get_db_type(), conn.db_type)
    provider = services.provider_factory(conn.db_type)
    summary: dict[str, Any] = {
        "name": conn.name,
        "db_type": conn.db_type,
        "db_type_label": db_type_label,
        "is_file_based": provider.metadata.is_file_based,
        "host": "",
        "port": "",
        "database": "",
        "username": "",
        "file_path": "",
        "auth_label": "N/A",
        "ssh_tunnel": False,
        "ssh_host": "",
        "source": conn.source or "",
        "folder_path": conn.folder_path or "",
    }
    if provider.metadata.is_file_based:
        file_endpoint = conn.file_endpoint
        summary["file_path"] = str(file_endpoint.path) if file_endpoint else ""
    else:
        endpoint = conn.tcp_endpoint
        if endpoint:
            summary["host"] = endpoint.host
            summary["port"] = endpoint.port
            summary["database"] = endpoint.database
            summary["username"] = endpoint.username
        if provider.metadata.has_advanced_auth:
            auth_value = str(conn.get_option("auth_type", ""))
            auth_type = provider.get_auth_type(conn)
            summary["auth_label"] = AUTH_TYPE_LABELS.get(auth_type, auth_value) if auth_type else auth_value
        elif endpoint and endpoint.username:
            summary["auth_label"] = f"User: {endpoint.username}"
    if conn.tunnel and conn.tunnel.enabled:
        summary["ssh_tunnel"] = True
        summary["ssh_host"] = conn.tunnel.host
    return summary


def _connection_info_str(s: dict[str, Any]) -> str:
    if s["is_file_based"]:
        return str(s["file_path"])
    host = str(s["host"])
    port = str(s["port"])
    db = str(s["database"])
    base = f"{host}:{port}" if port else host
    return f"{base}/{db}" if db else base


def cmd_connection_list(args: Any, *, services: AppServices | None = None) -> int:
    """List all saved connections."""
    import json as _json

    services = services or build_app_services(RuntimeConfig.from_env())
    connections = services.connection_store.load_all(load_credentials=False)

    fmt = getattr(args, "format", "table")
    verbose = bool(getattr(args, "verbose", False))

    if fmt == "json":
        payload = []
        for conn in connections:
            entry = conn.to_dict(include_passwords=False)
            entry["summary"] = _summarize_connection(conn, services)
            payload.append(entry)
        print(_json.dumps(payload, indent=2, default=str))
        return 0

    if not connections:
        print("No saved connections.")
        return 0

    summaries = [_summarize_connection(conn, services) for conn in connections]
    name_w = max(20, max(len(s["name"]) for s in summaries))
    type_w = max(15, max(len(s["db_type_label"]) for s in summaries))
    info_w = max(40, max(len(_connection_info_str(s)) for s in summaries))
    auth_w = max(20, max(len(s["auth_label"]) for s in summaries))

    if verbose:
        header = f"{'Name':<{name_w}}  {'Type':<{type_w}}  {'Connection Info':<{info_w}}  {'Auth':<{auth_w}}  SSH      Source"
    else:
        header = f"{'Name':<{name_w}}  {'Type':<{type_w}}  {'Connection Info':<{info_w}}  {'Auth':<{auth_w}}"
    print(header)
    print("-" * len(header))
    for s in summaries:
        info = _connection_info_str(s)
        line = f"{s['name']:<{name_w}}  {s['db_type_label']:<{type_w}}  {info:<{info_w}}  {s['auth_label']:<{auth_w}}"
        if verbose:
            ssh = f"{s['ssh_host']}" if s["ssh_tunnel"] else "-"
            line += f"  {ssh:<7}  {s['source']}"
        print(line)
    return 0


def cmd_connection_create(args: Any, *, services: AppServices | None = None) -> int:
    """Create a new connection."""
    from sqlit.domains.connections.app.url_parser import is_connection_url, parse_connection_url

    services = services or build_app_services(RuntimeConfig.from_env())
    connections = services.connection_store.load_all()

    # Handle URL-based connection creation
    url = getattr(args, "url", None)
    if url:
        if not is_connection_url(url):
            print(f"Error: Invalid connection URL: {url}")
            return 1

        url_name = getattr(args, "url_name", None)
        if not url_name:
            print("Error: --name is required when using --url")
            return 1

        if any(c.name == url_name for c in connections):
            print(f"Error: Connection '{url_name}' already exists. Use 'edit' to modify it.")
            return 1

        try:
            config = parse_connection_url(url, name=url_name)
        except ValueError as exc:
            print(f"Error: {exc}")
            return 1

        connections.append(config)
        has_db_password = bool(config.tcp_endpoint and config.tcp_endpoint.password)
        has_ssh_password = bool(config.tunnel and config.tunnel.password)
        if (has_db_password or has_ssh_password) and not is_keyring_usable():
            if not _maybe_prompt_plaintext_credentials(services):
                _clear_passwords_if_not_persisted(config)
        _save_connections(services, connections)
        print(f"Connection '{url_name}' created successfully.")
        return 0

    # Handle provider-based connection creation (existing behavior)
    if not getattr(args, "provider", None):
        print("Error: provider or --url is required.")
        print("Examples:")
        print("  sqlit connections add postgresql --name MyDB --server localhost ...")
        print("  sqlit connections add --url postgresql://user:pass@host/db --name MyDB")
        return 1

    if any(c.name == args.name for c in connections):
        print(f"Error: Connection '{args.name}' already exists. Use 'edit' to modify it.")
        return 1

    db_type = getattr(args, "provider", None)
    if not isinstance(db_type, str):
        print("Error: provider is required.")
        return 1
    try:
        DatabaseType(db_type)
    except ValueError:
        valid_types = ", ".join(t.value for t in DatabaseType)
        print(f"Error: Invalid database type '{db_type}'. Valid types: {valid_types}")
        return 1

    schema = get_provider_schema(db_type)
    try:
        config = build_connection_config_from_args(
            schema,
            args,
            name=args.name,
            default_name=None,
            strict=True,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    connections.append(config)
    _ensure_password_storage(services, config)
    _save_connections(services, connections)
    print(f"Connection '{args.name}' created successfully.")
    return 0


def cmd_connection_edit(args: Any, *, services: AppServices | None = None) -> int:
    """Edit an existing connection."""
    services = services or build_app_services(RuntimeConfig.from_env())
    connections = services.connection_store.load_all()

    conn_idx = _find_connection_index(connections, args.connection_name)
    if conn_idx is None:
        print(f"Error: Connection '{args.connection_name}' not found.")
        return 1

    conn = connections[conn_idx]

    if args.name:
        if args.name != conn.name and any(c.name == args.name for c in connections):
            print(f"Error: Connection '{args.name}' already exists.")
            return 1
        conn.name = args.name

    endpoint = conn.tcp_endpoint
    server = getattr(args, "server", None) or getattr(args, "host", None)
    if endpoint:
        if server:
            endpoint.host = server
        if args.port:
            endpoint.port = args.port
        if args.database:
            endpoint.database = args.database
    if args.auth_type:
        try:
            auth_type = AuthType(args.auth_type)
            conn.set_option("auth_type", auth_type.value)
            conn.set_option("trusted_connection", auth_type == AuthType.WINDOWS)
        except ValueError:
            valid_types = ", ".join(t.value for t in AuthType)
            print(f"Error: Invalid auth type '{args.auth_type}'. Valid types: {valid_types}")
            return 1
    if endpoint:
        if args.username is not None:
            endpoint.username = args.username
        if args.password is not None:
            endpoint.password = args.password

    password_command = getattr(args, "password_command", None)
    if password_command is not None and endpoint:
        endpoint.password_command = password_command or None

    ssh_password_command = getattr(args, "ssh_password_command", None)
    if ssh_password_command is not None and conn.tunnel:
        conn.tunnel.password_command = ssh_password_command or None

    file_path = getattr(args, "file_path", None)
    if file_path is not None:
        if conn.file_endpoint:
            conn.file_endpoint.path = file_path
        else:
            from sqlit.domains.connections.domain.config import FileEndpoint

            conn.endpoint = FileEndpoint(path=file_path)

    _ensure_password_storage(services, conn)

    _save_connections(services, connections)
    print(f"Connection '{conn.name}' updated successfully.")
    return 0


def cmd_connection_delete(args: Any, *, services: AppServices | None = None) -> int:
    """Delete a connection."""
    services = services or build_app_services(RuntimeConfig.from_env())
    connections = services.connection_store.load_all()

    conn_idx = _find_connection_index(connections, args.connection_name)
    if conn_idx is None:
        print(f"Error: Connection '{args.connection_name}' not found.")
        return 1

    deleted = connections.pop(conn_idx)
    _save_connections(services, connections)
    print(f"Connection '{deleted.name}' deleted successfully.")
    return 0


def cmd_docker_list(args: Any, *, services: AppServices | None = None) -> int:
    """List detected Docker database containers."""
    from sqlit.domains.connections.discovery.docker_detector import (
        ContainerStatus,
        DockerStatus,
    )

    services = services or build_app_services(RuntimeConfig.from_env())
    status, containers = services.docker_detector()

    if status == DockerStatus.NOT_INSTALLED:
        print("Error: Docker Python library not installed.")
        print("Install it with: pip install docker")
        return 1
    elif status == DockerStatus.NOT_RUNNING:
        print("Error: Docker is not running.")
        return 1
    elif status == DockerStatus.NOT_ACCESSIBLE:
        print("Error: Docker is not accessible (permission denied).")
        print("Try adding your user to the docker group or running with sudo.")
        return 1

    if not containers:
        print("No database containers found.")
        return 0

    running = [c for c in containers if c.status == ContainerStatus.RUNNING]
    exited = [c for c in containers if c.status == ContainerStatus.EXITED]

    print(f"{'Container':<25} {'Type':<12} {'Port':<8} {'Database':<15} {'Status':<10}")
    print("-" * 75)

    for c in running:
        port_str = str(c.port) if c.port else "-"
        db_str = c.database[:13] + ".." if c.database and len(c.database) > 15 else (c.database or "-")
        name_str = c.container_name[:23] + ".." if len(c.container_name) > 25 else c.container_name
        print(f"{name_str:<25} {c.db_type:<12} {port_str:<8} {db_str:<15} {'running':<10}")

    for c in exited:
        port_str = "-"
        db_str = c.database[:13] + ".." if c.database and len(c.database) > 15 else (c.database or "-")
        name_str = c.container_name[:23] + ".." if len(c.container_name) > 25 else c.container_name
        print(f"{name_str:<25} {c.db_type:<12} {port_str:<8} {db_str:<15} {'exited':<10}")

    print(f"\nFound {len(running)} running, {len(exited)} exited database container(s).")
    return 0
