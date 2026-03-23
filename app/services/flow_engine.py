"""Flow engine — executes flow touchpoints and handles node completion/transitions."""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.flow import FlowTouchpoint

logger = structlog.get_logger(__name__)


async def execute_touchpoint(db: AsyncSession, touchpoint: FlowTouchpoint) -> None:
    """Execute a single flow touchpoint (voice call, WhatsApp, etc.)."""
    logger.info(
        "flow_touchpoint_execute",
        touchpoint_id=str(touchpoint.id),
        node_type=touchpoint.node_snapshot.get("node_type") if touchpoint.node_snapshot else None,
    )
    # TODO: Implement per-node-type execution logic
    raise NotImplementedError("Flow touchpoint execution not yet implemented")


async def node_completed(
    tp_db: AsyncSession,
    touchpoint: FlowTouchpoint,
    outcome: str,
    outcome_data: dict | None = None,
) -> None:
    """Handle node completion — record transition and advance to next node."""
    logger.info(
        "flow_node_completed",
        touchpoint_id=str(touchpoint.id),
        outcome=outcome,
    )
    # TODO: Implement transition logic (evaluate edges, schedule next touchpoint)
    raise NotImplementedError("Flow node completion not yet implemented")
