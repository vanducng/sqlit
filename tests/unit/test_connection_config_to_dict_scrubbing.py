"""Regression tests: to_dict(include_passwords=False) must not leak credentials.

Covers both the structured endpoint/tunnel password fields and the
connection_url field (which embeds the password as URL userinfo when the
connection was created via `sqlit connections add --url`).
"""

from __future__ import annotations

from sqlit.domains.connections.domain.config import ConnectionConfig


def _make_url_connection(url: str) -> ConnectionConfig:
    return ConnectionConfig.from_dict(
        {
            "name": "from-url",
            "db_type": "postgresql",
            "server": "db.example.com",
            "port": "5432",
            "database": "appdb",
            "username": "appuser",
            "password": "s3cret-pw",
            "connection_url": url,
            "ssh_enabled": True,
            "ssh_host": "bastion.example.com",
            "ssh_port": "22",
            "ssh_username": "sshuser",
            "ssh_auth_type": "password",
            "ssh_password": "ssh-s3cret",
        }
    )


def test_to_dict_scrubs_endpoint_and_tunnel_passwords() -> None:
    conn = _make_url_connection("postgresql://appuser:s3cret-pw@db.example.com:5432/appdb")
    payload = conn.to_dict(include_passwords=False)

    assert payload["endpoint"]["password"] is None
    assert payload["tunnel"]["password"] is None
    # username retained for context
    assert payload["endpoint"]["username"] == "appuser"
    assert payload["tunnel"]["username"] == "sshuser"


def test_to_dict_scrubs_password_from_connection_url() -> None:
    conn = _make_url_connection("postgresql://appuser:s3cret-pw@db.example.com:5432/appdb")
    payload = conn.to_dict(include_passwords=False)

    assert "s3cret-pw" not in payload["connection_url"]
    # username + host + port + db preserved
    assert payload["connection_url"] == "postgresql://appuser@db.example.com:5432/appdb"


def test_to_dict_passwords_round_trip_when_requested() -> None:
    raw = "postgresql://appuser:s3cret-pw@db.example.com:5432/appdb"
    conn = _make_url_connection(raw)
    payload = conn.to_dict(include_passwords=True)

    assert payload["connection_url"] == raw
    assert payload["endpoint"]["password"] == "s3cret-pw"
    assert payload["tunnel"]["password"] == "ssh-s3cret"


def test_to_dict_handles_url_without_password() -> None:
    conn = _make_url_connection("postgresql://appuser@db.example.com/appdb")
    payload = conn.to_dict(include_passwords=False)

    assert payload["connection_url"] == "postgresql://appuser@db.example.com/appdb"


def test_to_dict_handles_no_connection_url() -> None:
    conn = ConnectionConfig.from_dict(
        {"name": "no-url", "db_type": "sqlite", "file_path": "/tmp/x.db"}
    )
    payload = conn.to_dict(include_passwords=False)

    assert payload["connection_url"] is None


def test_to_dict_full_payload_contains_no_known_secret() -> None:
    """Belt-and-suspenders: regardless of where it lives, the secret string
    must not appear anywhere in the JSON-bound payload."""
    import json

    conn = _make_url_connection("postgresql://appuser:s3cret-pw@db.example.com:5432/appdb")
    serialized = json.dumps(conn.to_dict(include_passwords=False))

    assert "s3cret-pw" not in serialized
    assert "ssh-s3cret" not in serialized
