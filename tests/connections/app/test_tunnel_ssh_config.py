"""Tests for SSH config integration with tunnel runtime."""

from __future__ import annotations

from unittest import mock

import pytest

pytest.importorskip("sshtunnel", reason="ssh extra not installed")


class TestTunnelManualPath:
    """Tests for manual SSH tunnel (existing behavior unchanged)."""

    def test_manual_path_unchanged(self):
        """source='manual' should produce today's kwargs (no change in behavior)."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="manual",
                host="bastion.example.com",
                port="22",
                username="ec2-user",
                auth_type="key",
                key_path="/home/user/.ssh/id_rsa",
            ),
        )

        with mock.patch("sshtunnel.SSHTunnelForwarder") as MockForwarder, mock.patch("pathlib.Path.exists", return_value=True):
            mock_tunnel = mock.MagicMock()
            mock_tunnel.local_bind_port = 54321
            MockForwarder.return_value = mock_tunnel

            from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

            _tunnel, host, port = create_ssh_tunnel(config)

            MockForwarder.assert_called_once()
            call_args = MockForwarder.call_args
            assert call_args[0][0] == ("bastion.example.com", 22)
            assert call_args[1]["ssh_username"] == "ec2-user"
            assert call_args[1]["ssh_pkey"] == "/home/user/.ssh/id_rsa"
            assert host == "127.0.0.1"
            assert port == 54321


class TestTunnelConfigMode:
    """Tests for SSH config alias mode."""

    def test_alias_direct_no_proxyjump(self):
        """Resolves alias, single SSHTunnelForwarder, correct kwargs."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="bastion",
            ),
        )

        with mock.patch("sshtunnel.SSHTunnelForwarder") as MockForwarder:
            mock_tunnel = mock.MagicMock()
            mock_tunnel.local_bind_port = 54321
            MockForwarder.return_value = mock_tunnel

            with mock.patch("sqlit.domains.connections.app.ssh_config.resolve") as mock_resolve:
                from sqlit.domains.connections.app.ssh_config import AliasInfo

                mock_resolve.return_value = AliasInfo(
                    name="bastion",
                    hostname="3.13.165.119",
                    user="ec2-user",
                    port=22,
                    identityfile="/home/user/.ssh/bastion_key",
                    proxyjump=None,
                )

                from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

                _tunnel, host, port = create_ssh_tunnel(config)

                mock_resolve.assert_called_once_with("bastion")
                MockForwarder.assert_called_once()
                call_args = MockForwarder.call_args
                assert call_args[0][0] == ("3.13.165.119", 22)
                assert call_args[1]["ssh_username"] == "ec2-user"
                assert call_args[1]["ssh_pkey"] == "/home/user/.ssh/bastion_key"
                assert host == "127.0.0.1"
                assert port == 54321

    def test_alias_with_proxyjump_chains(self):
        """Outer + inner both created, inner uses 127.0.0.1:<outer.local_bind_port>."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="db-server",
            ),
        )

        with mock.patch("sshtunnel.SSHTunnelForwarder") as MockForwarder:
            outer_tunnel = mock.MagicMock()
            outer_tunnel.local_bind_port = 12345
            inner_tunnel = mock.MagicMock()
            inner_tunnel.local_bind_port = 54321
            MockForwarder.side_effect = [outer_tunnel, inner_tunnel]

            with mock.patch("sqlit.domains.connections.app.ssh_config.resolve") as mock_resolve:
                from sqlit.domains.connections.app.ssh_config import AliasInfo

                mock_resolve.side_effect = [
                    AliasInfo(
                        name="db-server",
                        hostname="10.0.1.50",
                        user="admin",
                        port=2222,
                        identityfile="/home/user/.ssh/db_key",
                        proxyjump="bastion",
                    ),
                    AliasInfo(
                        name="bastion",
                        hostname="3.13.165.119",
                        user="ec2-user",
                        port=22,
                        identityfile="/home/user/.ssh/bastion_key",
                        proxyjump=None,
                    ),
                ]

                from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

                _tunnel, host, port = create_ssh_tunnel(config)

                assert mock_resolve.call_count == 2
                assert MockForwarder.call_count == 2

                outer_call = MockForwarder.call_args_list[0]
                assert outer_call[0][0] == ("3.13.165.119", 22)
                assert outer_call[1]["remote_bind_address"] == ("10.0.1.50", 2222)

                inner_call = MockForwarder.call_args_list[1]
                assert inner_call[0][0] == ("127.0.0.1", 12345)
                assert inner_call[1]["remote_bind_address"] == ("db.internal", 5432)

                assert host == "127.0.0.1"
                assert port == 54321

    def test_proxyjump_inner_failure_stops_outer(self):
        """inner .start() raises → outer .stop() called."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="db-server",
            ),
        )

        with mock.patch("sshtunnel.SSHTunnelForwarder") as MockForwarder:
            outer_tunnel = mock.MagicMock()
            outer_tunnel.local_bind_port = 12345
            inner_tunnel = mock.MagicMock()
            inner_tunnel.start.side_effect = Exception("Inner tunnel failed")
            MockForwarder.side_effect = [outer_tunnel, inner_tunnel]

            with mock.patch("sqlit.domains.connections.app.ssh_config.resolve") as mock_resolve:
                from sqlit.domains.connections.app.ssh_config import AliasInfo

                mock_resolve.side_effect = [
                    AliasInfo("db-server", "10.0.1.50", "admin", 2222, None, "bastion"),
                    AliasInfo("bastion", "3.13.165.119", "ec2-user", 22, None, None),
                ]

                from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

                with pytest.raises(Exception, match="Inner tunnel failed"):
                    create_ssh_tunnel(config)

                outer_tunnel.stop.assert_called_once()

    def test_chained_tunnel_stop_order(self):
        """stop() stops inner then outer."""
        from sqlit.domains.connections.app.tunnel import ChainedTunnel

        outer = mock.MagicMock()
        inner = mock.MagicMock()
        chain = ChainedTunnel(outer, inner)

        call_order = []
        inner.stop.side_effect = lambda: call_order.append("inner")
        outer.stop.side_effect = lambda: call_order.append("outer")

        chain.stop()

        assert call_order == ["inner", "outer"]
        inner.stop.assert_called_once()
        outer.stop.assert_called_once()

    def test_alias_missing_raises_not_found(self):
        """SSHAliasNotFoundError propagates."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="nonexistent",
            ),
        )

        with mock.patch("sqlit.domains.connections.app.ssh_config.resolve") as mock_resolve:
            from sqlit.domains.connections.app.ssh_config import SSHAliasNotFoundError

            mock_resolve.side_effect = SSHAliasNotFoundError("Alias 'nonexistent' not found")

            from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

            with pytest.raises(SSHAliasNotFoundError):
                create_ssh_tunnel(config)

    def test_alias_identityfile_none(self):
        """Key-less alias → ssh_pkey=None (paramiko agent fallback)."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        config = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432", database="mydb", username="user"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="keyless",
            ),
        )

        with mock.patch("sshtunnel.SSHTunnelForwarder") as MockForwarder:
            mock_tunnel = mock.MagicMock()
            mock_tunnel.local_bind_port = 54321
            MockForwarder.return_value = mock_tunnel

            with mock.patch("sqlit.domains.connections.app.ssh_config.resolve") as mock_resolve:
                from sqlit.domains.connections.app.ssh_config import AliasInfo

                mock_resolve.return_value = AliasInfo(
                    name="keyless",
                    hostname="keyless.example.com",
                    user="root",
                    port=22,
                    identityfile=None,
                    proxyjump=None,
                )

                from sqlit.domains.connections.app.tunnel import create_ssh_tunnel

                _tunnel, _host, _port = create_ssh_tunnel(config)

                call_args = MockForwarder.call_args
                assert call_args[1].get("ssh_pkey") is None


class TestTunnelConfigSerialization:
    """Tests for TunnelConfig serialization/deserialization."""

    def test_legacy_payload_loads_as_manual(self):
        """config.json w/o source field hydrates source='manual'."""
        from sqlit.domains.connections.domain.config import ConnectionConfig

        legacy_data = {
            "name": "test",
            "db_type": "postgresql",
            "endpoint": {"kind": "tcp", "host": "db.internal", "port": "5432"},
            "tunnel": {
                "enabled": True,
                "host": "bastion.example.com",
                "port": "22",
                "username": "ec2-user",
                "auth_type": "key",
                "key_path": "/home/user/.ssh/id_rsa",
            },
        }

        config = ConnectionConfig.from_dict(legacy_data)

        assert config.tunnel is not None
        assert config.tunnel.source == "manual"
        assert config.tunnel.host == "bastion.example.com"

    def test_source_config_payload_roundtrip(self):
        """save → load preserves source, config_alias; manual fields dropped."""
        from sqlit.domains.connections.domain.config import ConnectionConfig, TcpEndpoint, TunnelConfig

        original = ConnectionConfig(
            name="test",
            db_type="postgresql",
            endpoint=TcpEndpoint(host="db.internal", port="5432"),
            tunnel=TunnelConfig(
                enabled=True,
                source="config",
                config_alias="bastion",
            ),
        )

        serialized = original.to_dict()

        assert serialized["tunnel"]["source"] == "config"
        assert serialized["tunnel"]["config_alias"] == "bastion"
        assert "host" not in serialized["tunnel"]
        assert "username" not in serialized["tunnel"]

        reloaded = ConnectionConfig.from_dict(serialized)

        assert reloaded.tunnel is not None
        assert reloaded.tunnel.source == "config"
        assert reloaded.tunnel.config_alias == "bastion"
