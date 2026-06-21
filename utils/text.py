import re
import unicodedata

def normalize_speaker_name(name: str) -> str:
    """
    Normalize a Turkish political speaker name for consistent matching.

    Handles:
    - Twitter handles (strips @)
    - Party group prefixes (AK PARTİ GRUBU ADINA, CHP GRUBU ADINA, etc.)
    - Location suffixes in parentheses (e.g. "(İstanbul)")
    - Turkish character normalization (ş->s, ı->i, ç->c, ğ->g, ö->o, ü->u)
    - Case normalization and whitespace cleanup

    Examples:
        "Mehmet Şimşek" -> "mehmet simsek"
        "@memetsimsek" -> "memetsimsek"
        "AK PARTİ GRUBU ADINA Ahmet Çelik (İstanbul)" -> "ahmet celik"
    """
    if not name:
        return ""
        
    name = name.lstrip("@")
    
    prefixes = [
        "AK PARTİ GRUBU ADINA", "CHP GRUBU ADINA", "MHP GRUBU ADINA",
        "İYİ PARTİ GRUBU ADINA", "HDP GRUBU ADINA", "DEM PARTİ GRUBU ADINA",
        "YENİ YOL GRUBU ADINA", "TBMM BAŞKANI", "KOMİSYON BAŞKANI", "BAŞKAN",
    ]
    
    for prefix in prefixes:
        if name.upper().startswith(prefix):
            name = name[len(prefix):].strip()
            
    name = re.sub(r'\s*\([^)]*\)\s*$', '', name).strip()
    
    tr_map = {'ş':'s','Ş':'S','ı':'i','İ':'I','ç':'c','Ç':'C','ğ':'g','Ğ':'G','ö':'o','Ö':'O','ü':'u','Ü':'U'}
    for tr_char, ascii_char in tr_map.items():
        name = name.replace(tr_char, ascii_char)
        
    name = unicodedata.normalize('NFD', name)
    name = ''.join(c for c in name if unicodedata.category(c) != 'Mn')
    
    return re.sub(r'\s+', ' ', name.lower().strip())
