import json
from types import SimpleNamespace

from watchdock.ai_processor import AIProcessor, _extract_json_object
from watchdock.config import AIConfig


def test_missing_cloud_key_uses_review_only_rules(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("WATCHDOCK_OPENAI_API_KEY", raising=False)
    source = tmp_path / "Project Notes.txt"
    source.write_text("hello", encoding="utf-8")

    processor = AIProcessor(AIConfig(provider="openai"), examples_path=tmp_path / "x")
    result = processor.analyze_file(str(source))

    assert processor.available is False
    assert result["category"] == "Documents"
    assert result["requires_review"] is True
    assert result["analysis_source"] == "rules"
    assert "API key" in result["fallback_reason"]


def test_openai_uses_responses_structured_output_without_storage(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("meeting notes", encoding="utf-8")
    calls = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_text=json.dumps(
                    {
                        "category": "Documents",
                        "suggested_name": "meeting_notes.txt",
                        "tags": ["meeting"],
                        "description": "Notes from a meeting",
                    }
                )
            )

    client = SimpleNamespace(responses=Responses())
    processor = AIProcessor(
        AIConfig(provider="openai", model="test-model"),
        client=client,
        examples_path=tmp_path / "x",
    )

    result = processor.analyze_file(str(source))

    assert result["requires_review"] is False
    assert result["analysis_source"] == "openai"
    assert calls[0]["store"] is False
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    assert "<untrusted_file_preview>" in calls[0]["input"]


def test_invalid_provider_response_fails_closed(tmp_path):
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"not really an image")
    response = SimpleNamespace(output_text='{"category": 42}')
    client = SimpleNamespace(
        responses=SimpleNamespace(create=lambda **_kwargs: response)
    )
    processor = AIProcessor(
        AIConfig(provider="openai"),
        client=client,
        examples_path=tmp_path / "x",
    )

    result = processor.analyze_file(str(source))

    assert result["category"] == "Images"
    assert result["requires_review"] is True
    assert "invalid" in result["fallback_reason"]


def test_json_extractor_handles_fences_and_nested_values():
    payload = {"category": "Code", "meta": {"nested": True}, "tags": ["py"]}
    text = "Result:\n```json\n" + json.dumps(payload) + "\n```"

    assert _extract_json_object(text) == payload


def test_preview_is_limited(tmp_path):
    source = tmp_path / "big.txt"
    source.write_text("x" * 20_000, encoding="utf-8")

    preview = AIProcessor._read_file_preview(source, "text/plain", 123)

    assert preview == "x" * 123
