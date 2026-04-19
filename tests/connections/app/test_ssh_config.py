"""Tests for SSH config discovery module."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

import pytest


SSH_CONFIG_FIXTURE = """\
# Global settings
Host *
    AddKeysToAgent yes
    IdentitiesOnly yes

# Include statement (should not error, but not followed in v1)
Include config.d/*

Host bastion
    HostName 3.13.165.119
    User ec2-user
    Port 22
    IdentityFile ~/.ssh/bastion_key

Host db-server
    HostName 10.0.1.50
    User admin
    Port 2222
    IdentityFile ~/.ssh/db_key
    ProxyJump bastion

Host web-server
    HostName web.example.com
    User deploy

Host no-hostname
    User testuser
    Port 2200

Host keyless
    HostName keyless.example.com
    User root

Host multi-key
    HostName multi.example.com
    User ops
    IdentityFile ~/.ssh/key1
    IdentityFile ~/.ssh/key2

Host wildcard-*
    User wildcard

Host !negation
    User negated
"""


@pytest.fixture
def ssh_config_file(tmp_path: Path) -> Path:
    """Create a temporary SSH config file for testing."""
    config_path = tmp_path / "ssh_config"
    config_path.write_text(SSH_CONFIG_FIXTURE)
    return config_path


class TestListAliases:
    """Tests for list_aliases function."""

    def test_list_aliases_parses_fixture(self, ssh_config_file: Path):
        """Should parse fixture and return 8 aliases (excluding wildcards)."""
        from sqlit.domains.connections.app.ssh_config import list_aliases

        aliases = list_aliases(ssh_config_file)
        names = {a.name for a in aliases}
        assert len(aliases) == 6
        assert "bastion" in names
        assert "db-server" in names
        assert "web-server" in names
        assert "no-hostname" in names
        assert "keyless" in names
        assert "multi-key" in names

    def test_list_aliases_skips_wildcards(self, ssh_config_file: Path):
        """Host entries with *, ?, ! should be filtered from results."""
        from sqlit.domains.connections.app.ssh_config import list_aliases

        aliases = list_aliases(ssh_config_file)
        names = {a.name for a in aliases}
        assert "wildcard-*" not in names
        assert "!negation" not in names
        assert "*" not in names

    def test_list_aliases_ignores_include_directive(self, ssh_config_file: Path):
        """Include directive should parse without error; included files not followed."""
        from sqlit.domains.connections.app.ssh_config import list_aliases

        aliases = list_aliases(ssh_config_file)
        assert len(aliases) > 0

    def test_list_aliases_missing_file_returns_empty(self, tmp_path: Path):
        """Missing config file should return empty list, not raise."""
        from sqlit.domains.connections.app.ssh_config import list_aliases

        nonexistent = tmp_path / "nonexistent_config"
        result = list_aliases(nonexistent)
        assert result == []

    def test_list_aliases_missing_paramiko_returns_empty(self, ssh_config_file: Path, monkeypatch):
        """When paramiko is not installed, should return empty list."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "paramiko" or name.startswith("paramiko."):
                raise ImportError("No module named 'paramiko'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        if "sqlit.domains.connections.app.ssh_config" in sys.modules:
            del sys.modules["sqlit.domains.connections.app.ssh_config"]

        from sqlit.domains.connections.app.ssh_config import list_aliases

        result = list_aliases(ssh_config_file)
        assert result == []


class TestResolve:
    """Tests for resolve function."""

    def test_resolve_expanded_identityfile(self, ssh_config_file: Path):
        """IdentityFile with ~ should be expanded to absolute path."""
        from sqlit.domains.connections.app.ssh_config import resolve

        info = resolve("bastion", ssh_config_file)
        assert info.identityfile is not None
        assert info.identityfile.startswith(os.path.expanduser("~"))
        assert "bastion_key" in info.identityfile

    def test_resolve_captures_proxyjump(self, ssh_config_file: Path):
        """Host with ProxyJump should have proxyjump field set."""
        from sqlit.domains.connections.app.ssh_config import resolve

        info = resolve("db-server", ssh_config_file)
        assert info.proxyjump == "bastion"

    def test_resolve_missing_alias_raises(self, ssh_config_file: Path):
        """Non-existent alias should raise SSHAliasNotFoundError."""
        from sqlit.domains.connections.app.ssh_config import SSHAliasNotFoundError, resolve

        with pytest.raises(SSHAliasNotFoundError):
            resolve("nonexistent-alias", ssh_config_file)

    def test_resolve_missing_file_raises(self, tmp_path: Path):
        """Missing config file should raise FileNotFoundError."""
        from sqlit.domains.connections.app.ssh_config import resolve

        nonexistent = tmp_path / "nonexistent_config"
        with pytest.raises(FileNotFoundError):
            resolve("any-alias", nonexistent)

    def test_resolve_default_port_22(self, ssh_config_file: Path):
        """Host without Port should default to 22."""
        from sqlit.domains.connections.app.ssh_config import resolve

        info = resolve("web-server", ssh_config_file)
        assert info.port == 22

    def test_resolve_missing_paramiko_raises_missing_driver(self, ssh_config_file: Path, monkeypatch):
        """When paramiko is not installed, resolve should raise MissingDriverError."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "paramiko" or name.startswith("paramiko."):
                raise ImportError("No module named 'paramiko'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        if "sqlit.domains.connections.app.ssh_config" in sys.modules:
            del sys.modules["sqlit.domains.connections.app.ssh_config"]

        from sqlit.domains.connections.app.ssh_config import resolve
        from sqlit.domains.connections.providers.exceptions import MissingDriverError

        with pytest.raises(MissingDriverError) as exc_info:
            resolve("bastion", ssh_config_file)

        assert exc_info.value.extra_name == "ssh"
