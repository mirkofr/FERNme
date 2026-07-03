import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fernme.capture import CapturePipeline, build_adapters, default_config
from fernme.capture.extractors import extract_structured
from fernme.service import FernService
from fernme.store.sqlite_store import SQLiteStore


def _email(local="dana"):
    return local + "@example.test"


def _handle(name="dana_ops"):
    return "@" + name


def _phone_field():
    return "phone"


def test_extract_structured_contact_fields_are_regex_only():
    text = (
        "Reach " + _email() + " or +1 (555) 010-2222. "
        "See https://example.test/brief, " + _handle() + ", and 2026-07-03."
    )

    fields = extract_structured(text)

    assert ("email", _email()) in fields
    assert (_phone_field(), "+1 (555) 010-2222") in fields
    assert ("url", "https://example.test/brief") in fields
    assert ("handle", _handle()) in fields
    assert ("iso-date", "2026-07-03") in fields


def test_extract_structured_caps_count_and_value_length():
    many = " ".join(_email(f"user{i}") for i in range(20))
    too_long = "a" * 129 + "@example.test"

    fields = extract_structured(many + " " + too_long)

    assert len(fields) == 16
    assert all(len(value) <= 128 for _field, value in fields)


def test_extract_structured_drops_instruction_like_values():
    text = (
        "Keep " + _email("agent") + " but drop "
        "https://example.test/ignore-previous-instructions and "
        "https://example.test/prompt."
    )

    values = [value for _field, value in extract_structured(text)]

    assert _email("agent") in values
    assert all("ignore" not in value.lower() for value in values)
    assert all("prompt" not in value.lower() for value in values)


def _assert_pipeline_retains_structured_payload(adapter_name):
    svc = FernService(store=SQLiteStore(":memory:"))
    svc.store.set_consent("demo.com", "alex", True)
    pipe = CapturePipeline(
        svc,
        "demo.com",
        "alex",
        build_adapters(default_config(active=[adapter_name])),
    )
    text = "Reach " + _email() + " or +44 20 7946 0958."

    result = pipe.ingest({"kind": "chat", "text": text}, ts=7)
    event = svc.recall("demo.com", "alex", limit=1)[0]

    assert event["payload"]["structured"] == [
        ["email", _email()],
        [_phone_field(), "+44 20 7946 0958"],
    ]
    assert _email() in event["payload"]["text"]
    assert _email() not in result["stored_attrs"]
    assert "+44 20 7946 0958" not in result["stored_attrs"]


def test_pipeline_retains_structured_payload_for_agent_adapter():
    _assert_pipeline_retains_structured_payload("agent")


def test_pipeline_retains_structured_payload_for_local_adapter():
    _assert_pipeline_retains_structured_payload("local")


def test_pipeline_retains_structured_payload_for_signal_adapter():
    _assert_pipeline_retains_structured_payload("signal")
