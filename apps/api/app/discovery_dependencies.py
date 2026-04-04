from __future__ import annotations

from pydantic import BaseModel


class DependencyEdge(BaseModel):
    from_object: str
    to_object: str
    relationship_type: str


class DiscoveryGraph(BaseModel):
    run_id: str
    nodes: list[str]
    edges: list[DependencyEdge]


def build_sample_graph(run_id: str) -> DiscoveryGraph:
    return DiscoveryGraph(
        run_id=run_id,
        nodes=[
            "leasing.tenant_dim",
            "leasing.lease_fact",
            "mart.occupancy_by_region",
            "mart.revenue_by_tenant",
        ],
        edges=[
            DependencyEdge(
                from_object="leasing.tenant_dim",
                to_object="mart.revenue_by_tenant",
                relationship_type="feeds",
            ),
            DependencyEdge(
                from_object="leasing.lease_fact",
                to_object="mart.occupancy_by_region",
                relationship_type="feeds",
            ),
            DependencyEdge(
                from_object="leasing.lease_fact",
                to_object="mart.revenue_by_tenant",
                relationship_type="feeds",
            ),
        ],
    )
