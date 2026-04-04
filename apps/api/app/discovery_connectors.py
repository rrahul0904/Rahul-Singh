from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ConnectorCapability:
    name: str
    supports_metadata_scan: bool
    supports_dependency_scan: bool
    supports_complexity_scoring: bool


class DiscoveryConnector(Protocol):
    connector_type: str

    def capabilities(self) -> ConnectorCapability: ...


class TeradataDiscoveryConnector:
    connector_type = "teradata"

    def capabilities(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="Teradata",
            supports_metadata_scan=True,
            supports_dependency_scan=True,
            supports_complexity_scoring=True,
        )


class SqlServerDiscoveryConnector:
    connector_type = "sqlserver"

    def capabilities(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="SQL Server",
            supports_metadata_scan=True,
            supports_dependency_scan=True,
            supports_complexity_scoring=True,
        )


class OracleDiscoveryConnector:
    connector_type = "oracle"

    def capabilities(self) -> ConnectorCapability:
        return ConnectorCapability(
            name="Oracle",
            supports_metadata_scan=True,
            supports_dependency_scan=False,
            supports_complexity_scoring=True,
        )


def get_supported_connectors() -> list[ConnectorCapability]:
    connectors: list[DiscoveryConnector] = [
        TeradataDiscoveryConnector(),
        SqlServerDiscoveryConnector(),
        OracleDiscoveryConnector(),
    ]
    return [connector.capabilities() for connector in connectors]
