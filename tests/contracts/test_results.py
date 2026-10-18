from dataclasses import FrozenInstanceError, asdict

import pytest

from galmuri import Document, IngestResult, Processed
from galmuri.contracts.results import IngestResult as ContractResult
from galmuri.contracts.results import Processed as LegacyResult


def test_public_result_names_share_one_contract_and_wire_shape():
    assert IngestResult is ContractResult is Processed is LegacyResult
    document = Document("manual", "contents", readers=("*",))
    canonical = IngestResult((document,), ("parsed",))
    legacy = Processed((document,), ("parsed",))
    assert canonical == legacy
    assert isinstance(legacy, IngestResult)
    assert isinstance(canonical, Processed)
    assert canonical.__class__.__name__ == "IngestResult"
    assert (
        asdict(canonical)
        == asdict(legacy)
        == {
            "documents": (
                {
                    "key": "manual",
                    "text": "contents",
                    "metadata": {},
                    "readers": ("*",),
                    "writers": (),
                },
            ),
            "messages": ("parsed",),
        }
    )


def test_ingest_result_remains_frozen():
    result = IngestResult(())
    with pytest.raises(FrozenInstanceError):
        result.documents = ()


@pytest.mark.parametrize("result_type", [IngestResult, Processed])
def test_result_rejects_duplicate_document_identities(result_type):
    with pytest.raises(ValueError, match="duplicate document identities"):
        result_type((Document("same", "first"), Document("same", "second")))
