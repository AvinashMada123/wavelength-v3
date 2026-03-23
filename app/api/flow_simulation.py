"""
Flow simulation & live test endpoints.
Spec ref: §8.1, §8.2, §12 Simulation
"""
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_org
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flows", tags=["flow-simulation"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class SimulateRequest(BaseModel):
    mock_lead: dict[str, Any] = Field(..., description="Mock lead profile data")
    outcomes: dict[str, str] = Field(
        default_factory=dict,
        description="Manual outcome overrides: {node_id: outcome_label}",
    )

class SimulatePathStep(BaseModel):
    node_id: str
    node_type: str
    node_name: str
    action_preview: str | None = None
    outcome: str | None = None

class SimulateResponse(BaseModel):
    path: list[SimulatePathStep]
    goals_hit: list[str]
    end_reason: str  # "reached_end" | "goal_met" | "no_outgoing_edge" | "max_depth"

class LiveTestRequest(BaseModel):
    phone_number: str = Field(..., pattern=r"^\+\d{10,15}$")
    delay_ratio: int = Field(default=60, ge=1, le=1440, description="Delay compression ratio. 60 = 1hr→1min")

class LiveTestResponse(BaseModel):
    instance_id: str
    is_test: bool
    delay_ratio: int
    phone_number: str
    status: str

# ---------------------------------------------------------------------------
# Helpers (internal)
# ---------------------------------------------------------------------------

async def _get_version_graph(db: AsyncSession, flow_id: str, version_id: str, org_id: str):
    """Load nodes + edges for a flow version. Returns (nodes, edges, entry_node_id)."""
    # Import here to avoid circular deps — models defined in Plan 2
    from app.models.flow import FlowNode, FlowEdge, FlowVersion, FlowDefinition

    version = await db.get(FlowVersion, version_id)
    if not version or str(version.flow_id) != flow_id:
        raise HTTPException(status_code=404, detail="Flow version not found")

    # FlowVersion doesn't have org_id; verify via FlowDefinition
    flow_def = await db.get(FlowDefinition, version.flow_id)
    if not flow_def or str(flow_def.org_id) != org_id:
        raise HTTPException(status_code=404, detail="Flow version not found")

    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = list(nodes_result.scalars().all())

    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = list(edges_result.scalars().all())

    # Entry node = node with no incoming edges
    target_ids = {str(e.target_node_id) for e in edges}
    entry_nodes = [n for n in nodes if str(n.id) not in target_ids]
    if not entry_nodes:
        raise HTTPException(status_code=400, detail="Flow has no entry node")

    return nodes, edges, str(entry_nodes[0].id)


async def _get_entry_node_id(db: AsyncSession, version_id: str) -> str:
    from app.models.flow import FlowNode, FlowEdge

    nodes_result = await db.execute(
        select(FlowNode).where(FlowNode.version_id == version_id)
    )
    nodes = list(nodes_result.scalars().all())

    edges_result = await db.execute(
        select(FlowEdge).where(FlowEdge.version_id == version_id)
    )
    edges = list(edges_result.scalars().all())

    target_ids = {str(e.target_node_id) for e in edges}
    entry_nodes = [n for n in nodes if str(n.id) not in target_ids]
    if not entry_nodes:
        raise ValueError("No entry node found")
    return str(entry_nodes[0].id)


def _evaluate_condition(config: dict, lead: dict) -> str:
    """Evaluate condition node config against lead data. Returns matching label."""
    for condition in config.get("conditions", []):
        all_match = True
        for rule in condition.get("rules", []):
            field_val = lead.get(rule["field"])
            op = rule["operator"]
            target = rule["value"]
            if op == "eq" and field_val != target:
                all_match = False
            elif op == "neq" and field_val == target:
                all_match = False
            elif op == "gte" and (not isinstance(field_val, (int, float)) or field_val < target):
                all_match = False
            elif op == "gt" and (not isinstance(field_val, (int, float)) or field_val <= target):
                all_match = False
            elif op == "lte" and (not isinstance(field_val, (int, float)) or field_val > target):
                all_match = False
            elif op == "lt" and (not isinstance(field_val, (int, float)) or field_val >= target):
                all_match = False
            elif op == "contains" and (not isinstance(field_val, str) or target not in field_val):
                all_match = False
            elif op == "regex" and (not isinstance(field_val, str) or not re.search(target, field_val)):
                all_match = False
        if all_match:
            return condition["label"]
    return config.get("default_label", "default")


def _generate_preview(node) -> str | None:
    """Generate human-readable preview for action nodes."""
    nt = node.node_type
    cfg = node.config or {}
    if nt == "voice_call":
        return f"Voice call via bot {cfg.get('bot_id', 'default')}"
    elif nt == "whatsapp_template":
        return f"WhatsApp template: {cfg.get('template_name', 'unknown')}"
    elif nt == "whatsapp_session":
        return f"WhatsApp session message"
    elif nt == "ai_generate_send":
        return f"AI-generated {cfg.get('channel', 'message')}"
    elif nt == "delay_wait":
        return f"Wait {cfg.get('duration', '?')} {cfg.get('unit', 'hours')}"
    elif nt == "wait_for_event":
        return f"Wait for {cfg.get('event_type', 'event')}"
    elif nt == "goal_met":
        return f"Goal: {cfg.get('goal_name', 'unnamed')}"
    return None


async def _find_or_create_test_lead(db: AsyncSession, org_id: str, phone: str) -> str:
    """Find existing lead by phone or create a test lead. Returns lead_id."""
    from app.models.lead import Lead

    result = await db.execute(
        select(Lead).where(Lead.org_id == org_id, Lead.phone == phone)
    )
    existing = result.scalars().first()
    if existing:
        return str(existing.id)

    lead = Lead(
        id=uuid.uuid4(),
        org_id=org_id,
        name=f"Test Lead ({phone})",
        phone=phone,
        source="flow_test",
    )
    db.add(lead)
    await db.flush()
    return str(lead.id)


# ---------------------------------------------------------------------------
# Simulation (dry-run) — pure logic, no side effects
# ---------------------------------------------------------------------------

MAX_SIMULATION_DEPTH = 100

async def simulate_flow(
    db: AsyncSession,
    flow_id: str,
    version_id: str,
    org_id: str,
    mock_lead: dict,
    outcomes: dict[str, str],
) -> dict:
    """
    Walk the flow graph using mock lead data and optional manual outcomes.
    Returns the simulated path without creating any DB records.
    """
    nodes, edges, entry_id = await _get_version_graph(db, flow_id, version_id, org_id)

    node_map = {str(n.id): n for n in nodes}
    edges_by_source: dict[str, list] = {}
    for e in edges:
        src = str(e.source_node_id)
        edges_by_source.setdefault(src, []).append(e)

    path: list[dict] = []
    goals_hit: list[str] = []
    current_id = entry_id
    visited: set[str] = set()

    for _ in range(MAX_SIMULATION_DEPTH):
        if current_id in visited:
            break  # Cycle protection
        visited.add(current_id)

        node = node_map.get(current_id)
        if not node:
            break

        step = {
            "node_id": current_id,
            "node_type": node.node_type,
            "node_name": node.name,
            "action_preview": _generate_preview(node),
            "outcome": None,
        }

        # Terminal nodes
        if node.node_type == "end":
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "reached_end"}

        if node.node_type == "goal_met":
            goals_hit.append(node.config.get("goal_name", node.name))
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "goal_met"}

        # Determine outgoing edge
        outgoing = edges_by_source.get(current_id, [])
        if not outgoing:
            path.append(step)
            return {"path": path, "goals_hit": goals_hit, "end_reason": "no_outgoing_edge"}

        if node.node_type == "condition":
            # Check for manual override first
            if current_id in outcomes:
                label = outcomes[current_id]
            else:
                label = _evaluate_condition(node.config or {}, mock_lead)
            step["outcome"] = label
        else:
            label = "default"
            step["outcome"] = label

        # Find matching edge
        edge = next(
            (e for e in outgoing if e.condition_label == label),
            next((e for e in outgoing if e.condition_label == "default"), None),
        )

        path.append(step)

        if not edge:
            return {"path": path, "goals_hit": goals_hit, "end_reason": "no_outgoing_edge"}

        current_id = str(edge.target_node_id)

    return {"path": path, "goals_hit": goals_hit, "end_reason": "max_depth"}


# ---------------------------------------------------------------------------
# Live Test — creates real FlowInstance with is_test=true
# ---------------------------------------------------------------------------

PHONE_PATTERN = re.compile(r"^\+\d{10,15}$")

async def create_live_test(
    db: AsyncSession,
    flow_id: str,
    org_id: str,
    phone_number: str,
    delay_ratio: int = 60,
) -> dict:
    """Create a test FlowInstance with compressed delays."""
    if not PHONE_PATTERN.match(phone_number):
        raise ValueError("Please enter a valid phone number (e.g. +919876543210)")

    from app.models.flow import FlowVersion, FlowInstance, FlowDefinition

    # Find published version (FlowVersion has no org_id, join through FlowDefinition)
    result = await db.execute(
        select(FlowVersion)
        .join(FlowDefinition, FlowVersion.flow_id == FlowDefinition.id)
        .where(
            FlowVersion.flow_id == flow_id,
            FlowDefinition.org_id == org_id,
            FlowVersion.status == "published",
        )
    )
    version = result.scalars().first()
    if not version:
        raise HTTPException(status_code=400, detail="No published version. Publish the flow first.")

    lead_id = await _find_or_create_test_lead(db, org_id, phone_number)
    entry_node_id = await _get_entry_node_id(db, str(version.id))

    instance = FlowInstance(
        id=uuid.uuid4(),
        org_id=org_id,
        flow_id=flow_id,
        version_id=version.id,
        lead_id=lead_id,
        status="active",
        current_node_id=entry_node_id,
        is_test=True,
        context_data={"delay_ratio": delay_ratio, "test_phone": phone_number},
        started_at=datetime.now(timezone.utc),
    )
    db.add(instance)
    await db.commit()

    logger.info(f"Created live test instance {instance.id} for flow {flow_id} → {phone_number}")

    return {
        "instance_id": str(instance.id),
        "is_test": True,
        "delay_ratio": delay_ratio,
        "phone_number": phone_number,
        "status": "active",
    }


# ---------------------------------------------------------------------------
# Instance listing & journey helpers (used by tests + routes)
# ---------------------------------------------------------------------------

async def _query_instances(db: AsyncSession, flow_id: str, org_id: str, is_test: bool):
    """Query flow instances with optional is_test filter. Returns (instances, total)."""
    from app.models.flow import FlowInstance

    stmt = select(FlowInstance).where(
        FlowInstance.flow_id == flow_id,
        FlowInstance.org_id == org_id,
        FlowInstance.is_test == is_test,
    )
    result = await db.execute(stmt)
    instances = list(result.scalars().all())
    return instances, len(instances)


async def fetch_flow_instances(
    db: AsyncSession,
    flow_id: str,
    org_id: str,
    is_test: bool = False,
) -> dict:
    """Fetch flow instances, optionally filtering by is_test flag."""
    instances, total = await _query_instances(db, flow_id, org_id, is_test)
    return {
        "total": total,
        "instances": [
            {
                "id": str(inst.id),
                "is_test": inst.is_test,
                "status": inst.status,
                "lead_id": str(inst.lead_id),
            }
            for inst in instances
        ],
    }


async def _get_instance(db: AsyncSession, flow_id: str, instance_id: str):
    """Get a single flow instance by ID."""
    from app.models.flow import FlowInstance

    result = await db.execute(
        select(FlowInstance).where(
            FlowInstance.id == instance_id,
            FlowInstance.flow_id == flow_id,
        )
    )
    return result.scalars().first()


async def _get_touchpoints(db: AsyncSession, instance_id: str):
    """Get touchpoints for a flow instance."""
    from app.models.flow import FlowTouchpoint

    result = await db.execute(
        select(FlowTouchpoint).where(FlowTouchpoint.instance_id == instance_id)
        .order_by(FlowTouchpoint.scheduled_at.asc())
    )
    return list(result.scalars().all())


async def _get_transitions(db: AsyncSession, instance_id: str):
    """Get transitions for a flow instance."""
    from app.models.flow import FlowTransition

    result = await db.execute(
        select(FlowTransition).where(FlowTransition.instance_id == instance_id)
        .order_by(FlowTransition.transitioned_at.asc())
    )
    return list(result.scalars().all())


async def fetch_journey_data(
    db: AsyncSession,
    flow_id: str,
    instance_id: str,
    org_id: str,
) -> dict:
    """Fetch touchpoints + transitions for a flow instance journey."""
    instance = await _get_instance(db, flow_id, instance_id)
    if not instance:
        raise HTTPException(status_code=404, detail="Instance not found")

    touchpoints = await _get_touchpoints(db, instance_id)
    transitions = await _get_transitions(db, instance_id)

    return {
        "touchpoints": [
            {
                "id": str(tp.id),
                "node_id": str(tp.node_id),
                "status": tp.status,
                "outcome": tp.outcome,
                "scheduled_at": tp.scheduled_at.isoformat() if tp.scheduled_at else None,
                "executed_at": tp.executed_at.isoformat() if tp.executed_at else None,
                "completed_at": tp.completed_at.isoformat() if tp.completed_at else None,
            }
            for tp in touchpoints
        ],
        "transitions": [
            {
                "id": str(tr.id),
                "from_node_id": str(tr.from_node_id) if tr.from_node_id else None,
                "to_node_id": str(tr.to_node_id),
                "edge_id": str(tr.edge_id) if tr.edge_id else None,
                "outcome_data": tr.outcome_data,
                "transitioned_at": tr.transitioned_at.isoformat() if tr.transitioned_at else None,
            }
            for tr in transitions
        ],
    }


def compute_compressed_delay(delay_seconds: int, delay_ratio: int) -> int:
    """Compress a delay by the given ratio, with a minimum of 10 seconds."""
    compressed = delay_seconds // delay_ratio
    return max(compressed, 10)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/{flow_id}/versions/{version_id}/simulate", response_model=SimulateResponse)
async def api_simulate_flow(
    flow_id: str,
    version_id: str,
    body: SimulateRequest,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Dry-run simulation of a flow version with mock lead data."""
    result = await simulate_flow(
        db=db,
        flow_id=flow_id,
        version_id=version_id,
        org_id=str(org.id),
        mock_lead=body.mock_lead,
        outcomes=body.outcomes,
    )
    return result


@router.post("/{flow_id}/live-test", response_model=LiveTestResponse)
async def api_start_live_test(
    flow_id: str,
    body: LiveTestRequest,
    db: AsyncSession = Depends(get_db),
    org=Depends(get_current_org),
):
    """Start a live test with compressed delays."""
    try:
        result = await create_live_test(
            db=db,
            flow_id=flow_id,
            org_id=str(org.id),
            phone_number=body.phone_number,
            delay_ratio=body.delay_ratio,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
