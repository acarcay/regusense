import pytest
from datetime import datetime, timezone
from database.models import Base, normalize_speaker_name

def test_normalize_speaker_name():
    assert normalize_speaker_name("Mehmet Şimşek") == "mehmet simsek"
    assert normalize_speaker_name("@memetsimsek") == "memetsimsek"
    assert normalize_speaker_name("AK PARTİ GRUBU ADINA Ahmet Çelik (İstanbul)") == "ahmet celik"
    assert normalize_speaker_name("   İhsan   ÖZ  ") == "ihsan oz"
    assert normalize_speaker_name("") == ""
    assert normalize_speaker_name(None) == ""
