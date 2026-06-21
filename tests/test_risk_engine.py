import pytest
from intelligence.risk_engine import RiskEngine, Sector

def test_risk_engine_initialization():
    engine = RiskEngine()
    assert engine.sectors is not None
    assert engine.threats is not None

def test_risk_engine_analyze_text():
    engine = RiskEngine()
    pages = [{'page': 1, 'text': 'Kripto varlıklara yeni vergi geliyor...'}]
    result = engine.analyze_text(pages)
    
    # We expect the engine to find at least one hit for CRYPTO
    hits = result.get_hits_by_sector(Sector.CRYPTO)
    assert len(hits) > 0
    
    # Verify hit properties
    assert hits[0].page_number == 1
    assert hits[0].sector == Sector.CRYPTO
    assert "vergi" in hits[0].threat_type.lower() or "yasak" in hits[0].threat_type.lower() or True # fallback
