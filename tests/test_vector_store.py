"""
Unit tests for VectorStore.

Covers:
- Pure helper functions (_load_cases, _case_to_text, _case_to_metadata)
- Changed initialize_from_json behaviour: batched embedding, idempotency,
  retry logic, max-retry failure, and that load_existing() is called at the
  end so search() works without a separate call.
- search() guard when not initialised.
"""
import json
import pytest
from unittest.mock import MagicMock, call, patch

from src.vector_store import VectorStore


@pytest.fixture
def vs() -> VectorStore:
    return VectorStore()


# ---------------------------------------------------------------------------
# _load_cases
# ---------------------------------------------------------------------------

class TestLoadCases:
    def test_flat_list(self, vs, dataset_json_file, sample_case):
        cases = vs._load_cases(dataset_json_file)
        assert len(cases) == 1
        assert cases[0]["id"] == sample_case["id"]

    def test_wrapped_presentations_key(self, vs, dataset_json_file_wrapped, sample_case):
        cases = vs._load_cases(dataset_json_file_wrapped)
        assert len(cases) == 1
        assert cases[0]["id"] == sample_case["id"]

    def test_invalid_format_raises(self, vs, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"wrong_key": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unexpected dataset format"):
            vs._load_cases(str(bad))

    def test_empty_list(self, vs, tmp_path):
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        assert vs._load_cases(str(empty)) == []


# ---------------------------------------------------------------------------
# _case_to_text
# ---------------------------------------------------------------------------

class TestCaseToText:
    def test_contains_description(self, vs, sample_case):
        text = vs._case_to_text(sample_case)
        assert sample_case["patient_description"] in text

    def test_contains_chief_complaint(self, vs, sample_case):
        text = vs._case_to_text(sample_case)
        assert sample_case["chief_complaint"] in text

    def test_contains_symptoms(self, vs, sample_case):
        text = vs._case_to_text(sample_case)
        for symptom in sample_case["symptoms"]:
            assert symptom in text

    def test_contains_triage_decision(self, vs, sample_case):
        text = vs._case_to_text(sample_case)
        assert sample_case["triage_decision"] in text

    def test_missing_optional_fields_no_crash(self, vs):
        text = vs._case_to_text({})
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# _case_to_metadata
# ---------------------------------------------------------------------------

class TestCaseToMetadata:
    def test_returns_expected_keys(self, vs, sample_case):
        meta = vs._case_to_metadata(sample_case, 0)
        expected_keys = {
            "case_id", "triage_decision", "urgency_timeframe",
            "chief_complaint", "nice_guideline", "recommended_action", "confidence",
        }
        assert set(meta.keys()) == expected_keys

    def test_all_values_are_strings(self, vs, sample_case):
        meta = vs._case_to_metadata(sample_case, 0)
        for key, val in meta.items():
            assert isinstance(val, str), f"{key} should be str, got {type(val)}"

    def test_uses_fallback_case_id(self, vs):
        case = {"triage_decision": "GREEN"}
        meta = vs._case_to_metadata(case, 7)
        assert meta["case_id"] == "case_7"

    def test_uses_provided_id(self, vs, sample_case):
        meta = vs._case_to_metadata(sample_case, 0)
        assert meta["case_id"] == sample_case["id"]

    def test_triage_decision_preserved(self, vs, sample_case):
        meta = vs._case_to_metadata(sample_case, 0)
        assert meta["triage_decision"] == "RED"


# ---------------------------------------------------------------------------
# initialize_from_json — changed behaviour
# ---------------------------------------------------------------------------

def _make_mock_client(existing_ids: list[str] | None = None):
    """Return a mock chromadb PersistentClient with a mock collection."""
    mock_collection = MagicMock()
    mock_collection.get.return_value = {"ids": existing_ids or []}
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection
    return mock_client, mock_collection


def _make_mock_embeddings(return_value=None):
    mock_embeddings = MagicMock()
    mock_embeddings.embed_documents.return_value = return_value or [[0.1] * 8]
    return mock_embeddings


class TestInitializeFromJson:
    def test_calls_load_existing_at_end(self, vs, dataset_json_file):
        """After initialize_from_json, load_existing must be called so search works."""
        mock_client, _ = _make_mock_client()
        mock_embeddings = _make_mock_embeddings()

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing') as mock_load_existing, \
             patch('src.vector_store.time.sleep'):
            vs.initialize_from_json(dataset_json_file)

        mock_load_existing.assert_called_once()

    def test_vectorstore_not_none_after_initialize(self, vs, dataset_json_file):
        """search() must not raise 'not initialised' after initialize_from_json."""
        mock_client, _ = _make_mock_client()
        mock_embeddings = _make_mock_embeddings()

        def fake_load_existing():
            vs._vectorstore = MagicMock()

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing', side_effect=fake_load_existing), \
             patch('src.vector_store.time.sleep'):
            vs.initialize_from_json(dataset_json_file)

        assert vs._vectorstore is not None

    def test_skips_already_embedded_ids(self, vs, dataset_json_file, sample_case):
        """Cases whose IDs already exist in the collection must not be re-embedded."""
        mock_client, _ = _make_mock_client(existing_ids=[sample_case["id"]])
        mock_embeddings = _make_mock_embeddings()

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing'), \
             patch('src.vector_store.time.sleep'):
            vs.initialize_from_json(dataset_json_file)

        mock_embeddings.embed_documents.assert_not_called()

    def test_embeds_new_cases(self, vs, dataset_json_file):
        """Cases not yet in the collection must be embedded and added."""
        mock_client, mock_collection = _make_mock_client(existing_ids=[])
        mock_embeddings = _make_mock_embeddings()

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing'), \
             patch('src.vector_store.time.sleep'):
            vs.initialize_from_json(dataset_json_file)

        mock_embeddings.embed_documents.assert_called_once()
        mock_collection.add.assert_called_once()

    def test_retries_on_transient_failure(self, vs, dataset_json_file):
        """A failing embed_documents call must be retried."""
        mock_client, _ = _make_mock_client()
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = [
            Exception("429 quota"),
            Exception("429 quota"),
            [[0.1] * 8],           # succeeds on third attempt
        ]

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing'), \
             patch('src.vector_store.time.sleep') as mock_sleep:
            vs.initialize_from_json(dataset_json_file)

        assert mock_embeddings.embed_documents.call_count == 3
        assert mock_sleep.call_count == 2   # slept before attempt 2 and 3

    def test_raises_after_max_retries_exhausted(self, vs, dataset_json_file):
        """After 5 failed attempts the function must raise RuntimeError."""
        mock_client, _ = _make_mock_client()
        mock_embeddings = MagicMock()
        mock_embeddings.embed_documents.side_effect = Exception("persistent error")

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing'), \
             patch('src.vector_store.time.sleep'):
            with pytest.raises(RuntimeError, match="Failed to embed batch after retries"):
                vs.initialize_from_json(dataset_json_file)

        assert mock_embeddings.embed_documents.call_count == 5

    def test_batch_size_controls_chunk_count(self, vs, tmp_path):
        """With 6 cases and batch_size=2, embed_documents is called 3 times."""
        cases = [
            {"id": f"c{i}", "triage_decision": "GREEN", "symptoms": [],
             "past_medical_history": [], "red_flags_present": []}
            for i in range(6)
        ]
        path = tmp_path / "multi.json"
        path.write_text(json.dumps(cases), encoding="utf-8")

        mock_client, _ = _make_mock_client()
        mock_embeddings = _make_mock_embeddings([[0.1] * 8, [0.2] * 8])

        with patch.object(vs, '_get_chroma_client', return_value=mock_client), \
             patch.object(vs, '_get_embeddings', return_value=mock_embeddings), \
             patch.object(vs, 'load_existing'), \
             patch('src.vector_store.time.sleep'):
            vs.initialize_from_json(str(path), batch_size=2)

        assert mock_embeddings.embed_documents.call_count == 3


# ---------------------------------------------------------------------------
# search — guard: raises when not initialised
# ---------------------------------------------------------------------------

class TestSearchGuard:
    def test_raises_when_not_initialised(self, vs):
        with pytest.raises(RuntimeError, match="not initialised"):
            vs.search("test query")
