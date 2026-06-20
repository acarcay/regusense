import asyncio
import requests
from bs4 import BeautifulSoup
from datetime import datetime

from database.session import get_async_session
from database.models import Speaker, SpeakerRole, normalize_speaker_name
from database.neo4j_client import create_politician, create_political_party, add_politician_role
from sqlalchemy import select

WIKI_URL = "https://tr.wikipedia.org/wiki/TBMM_28._d%C3%B6nem_milletvekilleri_listesi"
DEFAULT_START_DATE = datetime.strptime("2023-06-02", "%Y-%m-%d").date()
DEFAULT_END_DATE = None

async def process_row(db_session, city, mp_name, party, change_note=""):
    """
    Process a single MP row and save it to PostgreSQL and Neo4j.
    """
    # Normalize name (remove citations like [1] or (politician))
    mp_name = mp_name.split("[")[0].split("(")[0].strip()
    norm_name = normalize_speaker_name(mp_name)
    
    if not norm_name:
        return

    # 1. POSTGRES: Create or Get Speaker
    result = await db_session.execute(select(Speaker).where(Speaker.normalized_name == norm_name))
    speaker = result.scalars().first()
    
    if not speaker:
        speaker = Speaker(name=mp_name, normalized_name=norm_name)
        db_session.add(speaker)
        await db_session.flush() # get ID
        
    # 2. POSTGRES: Create or Get SpeakerRole
    result_role = await db_session.execute(
        select(SpeakerRole).where(
            SpeakerRole.speaker_id == speaker.id,
            SpeakerRole.party == party,
            SpeakerRole.term_name == "28. Dönem"
        )
    )
    role = result_role.scalars().first()
    if not role:
        role = SpeakerRole(
            speaker_id=speaker.id,
            party=party,
            title="Milletvekili",
            term_name="28. Dönem",
            start_date=DEFAULT_START_DATE,
            end_date=DEFAULT_END_DATE
        )
        db_session.add(role)
        await db_session.commit()
    
    # 3 & 4. NEO4J: Sync Nodes and Relationships
    await create_politician(
        pg_id=speaker.id,
        name=mp_name,
        normalized_name=norm_name
    )
    
    await create_political_party(name=party, is_opposition=False)
    
    await add_politician_role(
        pg_id=speaker.id,
        party_name=party,
        title="Milletvekili",
        term_name="28. Dönem",
        start_date="2023-06-02",
        end_date=None
    )
    
    print(f"Eklendi: {mp_name} ({party}) - {city}")


async def main():
    print(f"Wikipedia'dan 28. dönem verileri çekiliyor... ({WIKI_URL})")
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(WIKI_URL, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    tables = soup.find_all("table", class_="wikitable")
    
    table = tables[5]
    rows = table.find_all("tr")[1:] # Skip header
    
    current_city = ""
    current_party = ""
    
    count = 0
    async with get_async_session() as db_session:
        for r in rows:
            cells = [td.text.strip() for td in r.find_all(["th", "td"])]
            
            if not cells:
                continue
                
            mp_name = ""
            party = ""
            change_note = ""
            
            # Handle rowspan and variable column lengths
            if len(cells) == 4:
                current_city = cells[0]
                mp_name = cells[1]
                current_party = cells[3]
            elif len(cells) == 6:
                current_city = cells[0]
                mp_name = cells[1]
                current_party = cells[3]
                change_note = cells[5]
            elif len(cells) == 1:
                mp_name = cells[0]
            elif len(cells) == 3:
                mp_name = cells[0]
                current_party = cells[2] 
            elif len(cells) == 5:
                mp_name = cells[0]
                current_party = cells[2]
                change_note = cells[4]
            else:
                print(f"Atlanıyor, bilinmeyen satır yapısı: {cells}")
                continue
                
            party = current_party
            
            await process_row(db_session, current_city, mp_name, party, change_note)
            count += 1
            
    print(f"\nVeri aktarımı tamamlandı! Toplam {count} milletvekili işlendi.")

if __name__ == "__main__":
    asyncio.run(main())
