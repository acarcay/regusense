import pytest
from intelligence.contradiction_engine import Evidence, ContradictionType

def test_evidence_to_dict():
    evidence = Evidence(
        text="Bu bir test açıklaması",
        date="2026-01-01",
        source="TBMM",
        topics=["ekonomi"]
    )
    
    d = evidence.to_dict()
    assert d["text"] == "Bu bir test açıklaması"
    assert d["date"] == "2026-01-01"
    assert d["source"] == "TBMM"
    assert "ekonomi" in d["topics"]

def test_contradiction_types():
    assert ContradictionType.REVERSAL.value == "REVERSAL"
    assert ContradictionType.NONE.value == "NONE"
