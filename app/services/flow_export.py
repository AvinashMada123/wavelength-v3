"""Flow export/import -- portable JSON format."""

import uuid
from copy import deepcopy
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import FlowDefinition, FlowEdge, FlowNode, FlowVersion

logger = structlog.get_logger(__name__)

# Fields to strip on export (org-specific)
_STRIP_FIELDS = {"org_id", "created_at", "updated_at"}


def strip_org_ids(data: dict[str, Any]) -> dict[str, Any]:
    """Remove org-specific IDs and replace DB UUIDs with portable temp IDs.

    Makes the exported JSON portable between organizations.
    """
    result = deepcopy(data)

    # Strip top-level org fields
    for field in _STRIP_FIELDS:
        result.pop(field, None)

    # Build ID -> temp_id map for nodes
    id_map: dict[str, str] = {}
    for node in result.get("nodes", []):
        old_id = node.pop("id", None)
        for field in _STRIP_FIELDS:
            node.pop(field, None)
        if old_id:
            temp_id = f"n_{uuid.uuid4().hex[:8]}"
            node["temp_id"] = temp_id
            id_map[str(old_id)] = temp_id

    # Remap edge references
    for edge in result.get("edges", []):
        edge.pop("id", None)
        for field in _STRIP_FIELDS:
            edge.pop(field, None)
        edge.pop("version_id", None)

        source = str(edge.pop("source_node_id", ""))
        target = str(edge.pop("target_node_id", ""))
        edge["source_temp_id"] = id_map.get(source, source)
        edge["target_temp_id"] = id_map.get(target, target)

    return result


def validate_import_payload(payload: dict[str, Any]) -> list[str]:
    """Validate an import payload. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not payload.get("name"):
        errors.append("Missing required field: name")

    nodes = payload.get("nodes", [])
    edges = payload.get("edges", [])

    if not any(n.get("node_type") == "end" for n in nodes):
        errors.append("Flow must have at least one End node")

    # Check for dangling edge references
    temp_ids = {n.get("temp_id") for n in nodes if n.get("temp_id")}
    for edge in edges:
        if edge.get("source_temp_id") not in temp_ids:
            errors.append(f"Dangling edge: missing source node {edge.get('source_temp_id')}")
        if edge.get("target_temp_id") not in temp_ids:
            errors.append(f"Dangling edge: missing target node {edge.get('target_temp_id')}")

    return errors


def prepare_import_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, uuid.UUID]]:
    """Map temp_ids to new UUIDs for import.

    Returns (mapped_nodes, mapped_edges, id_map).
    """
    id_map: dict[str, uuid.UUID] = {}

    # Assign new UUIDs to each temp_id
    for node in nodes:
        temp_id = node.get("temp_id", str(uuid.uuid4()))
        new_id = uuid.uuid4()
        id_map[temp_id] = new_id

    # Remap edges
    mapped_edges = []
    for edge in edges:
        source_temp = edge.get("source_temp_id", "")
        target_temp = edge.get("target_temp_id", "")
        mapped_edges.append({
            "source_node_id": id_map.get(source_temp),
            "target_node_id": id_map.get(target_temp),
            "condition_label": edge.get("condition_label", "default"),
            "sort_order": edge.get("sort_order", 0),
        })

    return nodes, mapped_edges, id_map


async def export_flow_version(
    db: AsyncSession,
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    org_id: uuid.UUID,
) -> dict[str, Any]:
    """Export a FlowVersion as portable JSON."""
    # Load flow definition
    flow_result = await db.execute(
        select(FlowDefinition).where(
            FlowDefinition.id == flow_id,
            FlowDefinition.org_id == org_id,
        )
    )
    flow = flow_result.scalar_one_or_none()
    if not flow:
        raise ValueError(f"Flow {flow_id} not found")

    # Load version
    ver_result = await db.execute(
        select(FlowVersion).where(
            FlowVersion.id == version_id,
            FlowVersion.flow_id == flow_id,
        )
    )
    version = ver_result.scalar_one_or_none()
    if not version:
        raise ValueError(f"Version {version_id} not found")

    # Load nodes
    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = nodes_result.scalars().all()

    # Load edges
    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = edges_result.scalars().all()

    # Build export dict
    export_data = {
        "name": flow.name,
        "description": flow.description,
        "trigger_type": flow.trigger_type,
        "trigger_config": flow.trigger_config,
        "org_id": str(org_id),
        "nodes": [
            {
                "id": str(n.id),
                "org_id": str(n.org_id),
                "node_type": n.node_type,
                "name": n.name,
                "position_x": n.position_x,
                "position_y": n.position_y,
                "config": n.config,
            }
            for n in nodes
        ],
        "edges": [
            {
                "id": str(e.id),
                "org_id": str(e.org_id),
                "source_node_id": str(e.source_node_id),
                "target_node_id": str(e.target_node_id),
                "condition_label": e.condition_label,
                "sort_order": e.sort_order,
            }
            for e in edges
        ],
    }

    # Strip org-specific data
    return strip_org_ids(export_data)


async def import_flow(
    db: AsyncSession,
    org_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    target_flow_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Import a flow from JSON. Creates new flow or new version of existing.

    Args:
        target_flow_id: If provided, creates a new version of this flow.
                        If None, creates a new FlowDefinition.
    """
    errors = validate_import_payload(payload)
    if errors:
        raise ValueError(f"Invalid import payload: {'; '.join(errors)}")

    nodes_data = payload.get("nodes", [])
    edges_data = payload.get("edges", [])
    _, mapped_edges, id_map = prepare_import_nodes(nodes_data, edges_data)

    if target_flow_id:
        # New version of existing flow
        flow_result = await db.execute(
            select(FlowDefinition).where(
                FlowDefinition.id == target_flow_id,
                FlowDefinition.org_id == org_id,
            )
        )
        flow = flow_result.scalar_one_or_none()
        if not flow:
            raise ValueError(f"Flow {target_flow_id} not found")

        # Get next version number
        ver_result = await db.execute(
            select(FlowVersion.version_number)
            .where(FlowVersion.flow_id == target_flow_id)
            .order_by(FlowVersion.version_number.desc())
            .limit(1)
        )
        last_ver = ver_result.scalar_one_or_none() or 0
        next_ver = last_ver + 1
    else:
        # New flow
        flow = FlowDefinition(
            org_id=org_id,
            name=payload.get("name", "Imported Flow"),
            description=payload.get("description", ""),
            trigger_type=payload.get("trigger_type", "manual"),
            trigger_config=payload.get("trigger_config", {}),
            is_active=False,
        )
        db.add(flow)
        await db.flush()
        next_ver = 1

    # Create version
    version = FlowVersion(
        flow_id=flow.id,
        org_id=org_id,
        version_number=next_ver,
        status="draft",
    )
    db.add(version)
    await db.flush()

    # Create nodes
    for node_data in nodes_data:
        temp_id = node_data.get("temp_id")
        real_id = id_map.get(temp_id)
        node = FlowNode(
            id=real_id,
            version_id=version.id,
            org_id=org_id,
            node_type=node_data["node_type"],
            name=node_data.get("name", ""),
            position_x=node_data.get("position_x", 0.0),
            position_y=node_data.get("position_y", 0.0),
            config=node_data.get("config", {}),
        )
        db.add(node)

    # Create edges
    for edge_data in mapped_edges:
        if edge_data["source_node_id"] and edge_data["target_node_id"]:
            edge = FlowEdge(
                version_id=version.id,
                org_id=org_id,
                source_node_id=edge_data["source_node_id"],
                target_node_id=edge_data["target_node_id"],
                condition_label=edge_data.get("condition_label", "default"),
                sort_order=edge_data.get("sort_order", 0),
            )
            db.add(edge)

    await db.flush()

    return {
        "flow_id": str(flow.id),
        "version_id": str(version.id),
        "version_number": next_ver,
        "node_count": len(nodes_data),
        "edge_count": len(mapped_edges),
        "status": "draft",
    }
