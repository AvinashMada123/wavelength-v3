"""Tests for flow export/import JSON format."""

import uuid
from datetime import datetime

import pytest

from app.services.flow_export import (
    export_flow_version,
    strip_org_ids,
    validate_import_payload,
    prepare_import_nodes,
)


class TestStripOrgIds:
    """Exported JSON must not contain org-specific UUIDs."""

    def test_strips_org_id(self):
        data = {
            "org_id": str(uuid.uuid4()),
            "name": "My Flow",
            "nodes": [
                {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "name": "Call"},
            ],
            "edges": [
                {"id": str(uuid.uuid4()), "org_id": str(uuid.uuid4()), "source_node_id": "a", "target_node_id": "b"},
            ],
        }
        cleaned = strip_org_ids(data)
        assert "org_id" not in cleaned
        assert "org_id" not in cleaned["nodes"][0]
        assert "org_id" not in cleaned["edges"][0]

    def test_preserves_non_org_fields(self):
        data = {"name": "Flow", "description": "Test", "org_id": "x"}
        cleaned = strip_org_ids(data)
        assert cleaned["name"] == "Flow"
        assert cleaned["description"] == "Test"

    def test_strips_db_ids(self):
        """Export should replace UUIDs with portable temp IDs."""
        node_id = str(uuid.uuid4())
        data = {
            "nodes": [{"id": node_id, "name": "Call"}],
            "edges": [{"id": str(uuid.uuid4()), "source_node_id": node_id, "target_node_id": node_id}],
        }
        cleaned = strip_org_ids(data)
        # IDs should be replaced or removed
        assert cleaned["nodes"][0].get("id") != node_id


class TestValidateImportPayload:
    """Import validation checks."""

    def test_valid_payload(self):
        payload = {
            "name": "Imported Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}, "position_x": 0, "position_y": 0},
                {"temp_id": "n2", "node_type": "end", "name": "End", "config": {}, "position_x": 0, "position_y": 200},
            ],
            "edges": [
                {"source_temp_id": "n1", "target_temp_id": "n2", "condition_label": "default"},
            ],
        }
        errors = validate_import_payload(payload)
        assert len(errors) == 0

    def test_missing_name(self):
        payload = {"nodes": [], "edges": []}
        errors = validate_import_payload(payload)
        assert any("name" in e.lower() for e in errors)

    def test_missing_end_node(self):
        payload = {
            "name": "Bad Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}},
            ],
            "edges": [],
        }
        errors = validate_import_payload(payload)
        assert any("end" in e.lower() for e in errors)

    def test_dangling_edge_reference(self):
        payload = {
            "name": "Bad Flow",
            "nodes": [
                {"temp_id": "n1", "node_type": "end", "name": "End", "config": {}},
            ],
            "edges": [
                {"source_temp_id": "n1", "target_temp_id": "n_missing", "condition_label": "default"},
            ],
        }
        errors = validate_import_payload(payload)
        assert any("dangling" in e.lower() or "missing" in e.lower() for e in errors)


class TestPrepareImportNodes:
    """Map temp IDs to new UUIDs for import."""

    def test_maps_temp_ids_to_uuids(self):
        nodes = [
            {"temp_id": "n1", "node_type": "voice_call", "name": "Call", "config": {}},
            {"temp_id": "n2", "node_type": "end", "name": "End", "config": {}},
        ]
        edges = [{"source_temp_id": "n1", "target_temp_id": "n2", "condition_label": "default"}]

        mapped_nodes, mapped_edges, id_map = prepare_import_nodes(nodes, edges)

        assert "n1" in id_map
        assert "n2" in id_map
        assert id_map["n1"] != id_map["n2"]
        assert mapped_edges[0]["source_node_id"] == id_map["n1"]
        assert mapped_edges[0]["target_node_id"] == id_map["n2"]
