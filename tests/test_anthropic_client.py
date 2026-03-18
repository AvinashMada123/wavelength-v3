import sys
from types import SimpleNamespace
from unittest.mock import Mock

sys.modules.setdefault("structlog", SimpleNamespace(get_logger=lambda *a, **k: Mock()))


def test_interpolate_variables():
    from app.services.anthropic_client import _interpolate_variables
    prompt = "Hello {{name}}, you are a {{profession}} who {{challenge}}."
    variables = {"name": "Amuthan", "profession": "software engineer", "challenge": "wants to learn AI"}
    result = _interpolate_variables(prompt, variables)
    assert result == "Hello Amuthan, you are a software engineer who wants to learn AI."


def test_interpolate_missing_variable_left_as_is():
    from app.services.anthropic_client import _interpolate_variables
    prompt = "Hello {{name}}, your score is {{score}}."
    variables = {"name": "Amuthan"}
    result = _interpolate_variables(prompt, variables)
    assert result == "Hello Amuthan, your score is {{score}}."


def test_interpolate_empty_variables():
    from app.services.anthropic_client import _interpolate_variables
    result = _interpolate_variables("No vars here", {})
    assert result == "No vars here"


def test_extract_variable_names():
    from app.services.anthropic_client import extract_variable_names
    prompt = "{{name}} is a {{profession}} from {{city}}. {{name}} again."
    names = extract_variable_names(prompt)
    assert names == {"name", "profession", "city"}
