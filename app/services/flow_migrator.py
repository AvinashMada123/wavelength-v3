"""Migrate SequenceTemplate -> FlowDefinition + FlowVersion.

Converts linear sequence steps into a chain of FlowNodes with edges.
Handles channel mapping, timing-to-delay conversion, and skip_conditions-to-condition conversion.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sequence import SequenceStep, SequenceTemplate
from app.models.flow import FlowDefinition, FlowEdge, FlowNode, FlowVersion

logger = structlog.get_logger(__name__)

# -- Channel mapping ----------------------------------------------------------

CHANNEL_MAP: dict[str, str] = {
    "voice_call": "voice_call",
    "whatsapp_template": "whatsapp_template",
    "whatsapp_session": "whatsapp_session",
    "ai_message": "ai_generate_send",
    "ai_generated": "ai_generate_send",
}


def map_channel_to_node_type(channel: str) -> str:
    """Map a SequenceStep.channel value to a FlowNode.node_type."""
    node_type = CHANNEL_MAP.get(channel)
    if node_type is None:
        raise ValueError(f"Unknown channel: {channel}")
    return node_type


# -- Step -> Node conversion ---------------------------------------------------

def convert_step_to_node(step: dict[str, Any], step_index: int) -> dict[str, Any]:
    """Convert a single SequenceStep snapshot to a FlowNode dict.

    Returns a dict with: node_type, name, config, position_x, position_y.
    """
    channel = step["channel"]
    content_type = step.get("content_type", "")

    # Determine node_type based on channel + content_type
    if content_type == "ai_generated":
        node_type = "ai_generate_send"
    else:
        node_type = map_channel_to_node_type(channel)

    # Build node-type-specific config
    config: dict[str, Any] = {}

    if node_type == "voice_call":
        config["bot_id"] = step.get("voice_bot_id")
        config["quick_retry"] = {"enabled": False, "max_attempts": 1, "interval_hours": 1}
        config["send_window"] = {"enabled": False}

    elif node_type == "whatsapp_template":
        config["template_name"] = step.get("whatsapp_template_name", "")
        config["params"] = step.get("whatsapp_template_params") or {}

    elif node_type == "whatsapp_session":
        config["message_type"] = "text"
        config["text_body"] = ""
        if step.get("expects_reply"):
            config["wait_for_reply"] = True
            config["reply_timeout_hours"] = 24
        else:
            config["wait_for_reply"] = False

    elif node_type == "ai_generate_send":
        config["prompt"] = step.get("ai_prompt", "")
        config["model"] = step.get("ai_model", "claude-sonnet")
        config["send_via"] = channel if channel != "ai_message" else "whatsapp_session"
        config["max_tokens"] = 500

    # Canvas position: vertical chain layout
    position_x = 400.0
    position_y = 100.0 + (step_index * 200.0)

    return {
        "node_type": node_type,
        "name": step.get("name", f"Step {step_index + 1}"),
        "config": config,
        "position_x": position_x,
        "position_y": position_y,
    }


# -- Skip conditions -> Condition node -----------------------------------------

def convert_skip_conditions_to_condition_node(
    skip_conditions: dict[str, Any] | None,
    step_name: str,
) -> dict[str, Any] | None:
    """Convert a step's skip_conditions to a Condition FlowNode.

    The linear engine skips the step when condition matches.
    In the flow graph, a Condition node branches:
      - "skip" edge -> next step (bypass this one)
      - "default" edge -> this step (execute it)
    """
    if not skip_conditions:
        return None

    field = skip_conditions.get("field", "")
    rules = []

    if "equals" in skip_conditions:
        rules.append({
            "field": field,
            "operator": "equals",
            "value": skip_conditions["equals"],
        })
    elif "not_equals" in skip_conditions:
        rules.append({
            "field": field,
            "operator": "not_equals",
            "value": skip_conditions["not_equals"],
        })

    if not rules:
        return None

    return {
        "node_type": "condition",
        "name": f"Check before {step_name}",
        "config": {
            "logic": "and",
            "rules": rules,
        },
        "position_x": 400.0,
        "position_y": 0.0,  # Will be repositioned in build_flow_graph
    }


# -- Timing -> Delay node ------------------------------------------------------

def map_timing_to_delay_node(
    timing_type: str, timing_value: dict[str, Any]
) -> dict[str, Any] | None:
    """Convert timing_type + timing_value to a Delay/Wait FlowNode.

    Returns None for 'immediate' timing (no delay needed).
    """
    if timing_type == "immediate":
        return None

    config: dict[str, Any] = {}

    if timing_type == "delay":
        total_hours = (
            timing_value.get("days", 0) * 24
            + timing_value.get("hours", 0)
            + timing_value.get("minutes", 0) / 60
        )
        config["delay_hours"] = total_hours
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]

    elif timing_type == "relative_to_event":
        config["relative_to"] = timing_value.get("event_variable", "event_date")
        config["offset_days"] = timing_value.get("days", 0)
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]
        config["delay_hours"] = abs(timing_value.get("days", 0)) * 24

    elif timing_type == "relative_to_previous":
        total_hours = (
            timing_value.get("days", 0) * 24
            + timing_value.get("hours", 0)
            + timing_value.get("minutes", 0) / 60
        )
        config["delay_hours"] = total_hours
        if "time" in timing_value:
            config["at_time"] = timing_value["time"]

    else:
        logger.warning("unknown_timing_type", timing_type=timing_type)
        config["delay_hours"] = 0

    return {
        "node_type": "delay_wait",
        "name": "Wait",
        "config": config,
        "position_x": 400.0,
        "position_y": 0.0,
    }


# -- Build full flow graph -----------------------------------------------------

def build_flow_graph(
    steps: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert an ordered list of step snapshots into nodes + edges.

    Returns (nodes, edges) where each node has a temporary 'temp_id' for edge linking,
    and each edge has 'source_temp_id' and 'target_temp_id'.
    """
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    if not steps:
        nodes.append({
            "temp_id": str(uuid.uuid4()),
            "node_type": "end",
            "name": "End",
            "config": {"end_reason": "completed"},
            "position_x": 400.0,
            "position_y": 100.0,
        })
        return nodes, edges

    y_cursor = 100.0
    prev_temp_id: str | None = None

    for i, step in enumerate(steps):
        # 1) Delay node (if timing is not immediate and not first step)
        delay_node = None
        if i > 0:  # First step timing is handled by enrollment
            delay_node = map_timing_to_delay_node(
                step.get("timing_type", "immediate"),
                step.get("timing_value", {}),
            )

        if delay_node:
            delay_temp_id = str(uuid.uuid4())
            delay_node["temp_id"] = delay_temp_id
            delay_node["position_y"] = y_cursor
            nodes.append(delay_node)

            if prev_temp_id:
                edges.append({
                    "source_temp_id": prev_temp_id,
                    "target_temp_id": delay_temp_id,
                    "condition_label": "default",
                    "sort_order": 0,
                })
            prev_temp_id = delay_temp_id
            y_cursor += 150.0

        # 2) Condition node (if skip_conditions exist)
        skip_cond = step.get("skip_conditions")
        cond_node = convert_skip_conditions_to_condition_node(skip_cond, step.get("name", ""))

        if cond_node:
            cond_temp_id = str(uuid.uuid4())
            cond_node["temp_id"] = cond_temp_id
            cond_node["position_y"] = y_cursor
            nodes.append(cond_node)

            if prev_temp_id:
                edges.append({
                    "source_temp_id": prev_temp_id,
                    "target_temp_id": cond_temp_id,
                    "condition_label": "default",
                    "sort_order": 0,
                })

            # "default" edge connects to this step's action node
            cond_prev_id = cond_temp_id
            y_cursor += 150.0
        else:
            cond_prev_id = None

        # 3) Action node
        action = convert_step_to_node(step, step_index=i)
        action_temp_id = str(uuid.uuid4())
        action["temp_id"] = action_temp_id
        action["position_y"] = y_cursor
        nodes.append(action)

        if cond_prev_id:
            # Condition -> action (default path = condition NOT met, so execute)
            edges.append({
                "source_temp_id": cond_prev_id,
                "target_temp_id": action_temp_id,
                "condition_label": "default",
                "sort_order": 1,
            })
        elif prev_temp_id:
            edges.append({
                "source_temp_id": prev_temp_id,
                "target_temp_id": action_temp_id,
                "condition_label": "default",
                "sort_order": 0,
            })

        prev_temp_id = action_temp_id
        y_cursor += 150.0

    # 4) End node
    end_temp_id = str(uuid.uuid4())
    nodes.append({
        "temp_id": end_temp_id,
        "node_type": "end",
        "name": "End",
        "config": {"end_reason": "completed"},
        "position_x": 400.0,
        "position_y": y_cursor,
    })

    if prev_temp_id:
        edges.append({
            "source_temp_id": prev_temp_id,
            "target_temp_id": end_temp_id,
            "condition_label": "default",
            "sort_order": 0,
        })

    # 5) Resolve skip-condition "skip" edges
    cond_indices = [i for i, n in enumerate(nodes) if n["node_type"] == "condition"]
    for ci in cond_indices:
        cond = nodes[ci]
        # Find the action node right after this condition
        action_idx = ci + 1
        if action_idx >= len(nodes):
            continue
        # Find the node after the action (next delay, condition, or end)
        skip_target_idx = action_idx + 1
        if skip_target_idx >= len(nodes):
            skip_target_idx = len(nodes) - 1  # End node

        edges.append({
            "source_temp_id": cond["temp_id"],
            "target_temp_id": nodes[skip_target_idx]["temp_id"],
            "condition_label": "skip",
            "sort_order": 0,
        })

    return nodes, edges


# -- DB-level migration --------------------------------------------------------

async def migrate_template(
    db: AsyncSession,
    template_id: uuid.UUID,
    org_id: uuid.UUID,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Convert a SequenceTemplate into a FlowDefinition + FlowVersion (draft).

    Returns a summary dict with flow_id, version_id, node_count, edge_count.
    If dry_run=True, returns the summary without persisting.
    """
    # Load template
    tmpl_result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.id == template_id,
            SequenceTemplate.org_id == org_id,
        )
    )
    template = tmpl_result.scalar_one_or_none()
    if template is None:
        raise ValueError(f"Template {template_id} not found for org {org_id}")

    # Load steps
    steps_result = await db.execute(
        select(SequenceStep)
        .where(
            SequenceStep.template_id == template_id,
            SequenceStep.is_active == True,  # noqa: E712
        )
        .order_by(SequenceStep.step_order)
    )
    steps = steps_result.scalars().all()

    # Snapshot steps
    step_dicts = []
    for s in steps:
        step_dicts.append({
            "step_order": s.step_order,
            "name": s.name,
            "channel": s.channel,
            "content_type": s.content_type,
            "timing_type": s.timing_type,
            "timing_value": s.timing_value,
            "skip_conditions": s.skip_conditions,
            "whatsapp_template_name": s.whatsapp_template_name,
            "whatsapp_template_params": s.whatsapp_template_params,
            "ai_prompt": s.ai_prompt,
            "ai_model": s.ai_model,
            "voice_bot_id": str(s.voice_bot_id) if s.voice_bot_id else None,
            "expects_reply": s.expects_reply,
            "reply_handler": s.reply_handler,
        })

    # Build graph
    nodes_data, edges_data = build_flow_graph(step_dicts)

    summary = {
        "template_id": str(template_id),
        "template_name": template.name,
        "node_count": len(nodes_data),
        "edge_count": len(edges_data),
        "nodes": [{"name": n["name"], "type": n["node_type"]} for n in nodes_data],
    }

    if dry_run:
        summary["dry_run"] = True
        return summary

    # Create FlowDefinition
    flow = FlowDefinition(
        org_id=org_id,
        name=f"{template.name} (migrated)",
        description=f"Auto-converted from linear sequence '{template.name}'",
        trigger_type=template.trigger_type,
        trigger_config=template.trigger_conditions,
        is_active=False,  # Draft -- must be reviewed before activating
    )
    db.add(flow)
    await db.flush()

    # Create FlowVersion (draft)
    version = FlowVersion(
        flow_id=flow.id,
        org_id=org_id,
        version_number=1,
        status="draft",
    )
    db.add(version)
    await db.flush()

    # Create nodes -- map temp_id -> real UUID
    temp_to_real: dict[str, uuid.UUID] = {}
    for node_data in nodes_data:
        node = FlowNode(
            version_id=version.id,
            org_id=org_id,
            node_type=node_data["node_type"],
            name=node_data["name"],
            position_x=node_data["position_x"],
            position_y=node_data["position_y"],
            config=node_data["config"],
        )
        db.add(node)
        await db.flush()
        temp_to_real[node_data["temp_id"]] = node.id

    # Create edges
    for edge_data in edges_data:
        source_id = temp_to_real.get(edge_data["source_temp_id"])
        target_id = temp_to_real.get(edge_data["target_temp_id"])
        if source_id and target_id:
            edge = FlowEdge(
                version_id=version.id,
                org_id=org_id,
                source_node_id=source_id,
                target_node_id=target_id,
                condition_label=edge_data["condition_label"],
                sort_order=edge_data["sort_order"],
            )
            db.add(edge)

    await db.flush()

    summary["flow_id"] = str(flow.id)
    summary["version_id"] = str(version.id)
    summary["status"] = "draft"

    logger.info(
        "template_migrated_to_flow",
        template_id=str(template_id),
        flow_id=str(flow.id),
        node_count=len(nodes_data),
        edge_count=len(edges_data),
    )

    return summary


async def migrate_all_templates(
    db: AsyncSession,
    org_id: uuid.UUID,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Migrate all active SequenceTemplates for an org to FlowDefinitions.

    Returns a list of summary dicts.
    """
    result = await db.execute(
        select(SequenceTemplate).where(
            SequenceTemplate.org_id == org_id,
            SequenceTemplate.is_active == True,  # noqa: E712
        )
    )
    templates = result.scalars().all()

    summaries = []
    for template in templates:
        try:
            summary = await migrate_template(
                db, template.id, org_id, dry_run=dry_run,
            )
            summaries.append(summary)
        except Exception as e:
            logger.exception(
                "template_migration_failed",
                template_id=str(template.id),
                error=str(e),
            )
            summaries.append({
                "template_id": str(template.id),
                "template_name": template.name,
                "error": str(e),
            })

    return summaries
