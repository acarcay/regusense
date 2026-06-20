import os
import re
import asyncio
import pdfplumber

from database.session import get_async_session
from database.models import Speaker, Statement, RawDocument, DocumentType, normalize_speaker_name, generate_content_hash
from database.neo4j_client import create_speech, add_made_speech_relation
from sqlalchemy import select

# Sadece test amaçlı tek bir dosya ve 5 sayfa
TEST_FILE = "/Users/acar/Desktop/tbmm_tutanak/28.dönem/1.yasamayılı/tbmm28001004.pdf"
TERM_NAME = "28. Dönem"

async def process_pdf():
    print(f"İşleniyor: {TEST_FILE}")
    
    full_text = ""
    with pdfplumber.open(TEST_FILE) as pdf:
        for page in pdf.pages[20:25]:  # Sayfa 20-25 arası (konuşmaların olduğu kısım)
            full_text += page.extract_text() + "\n"
            
    # Konuşmacıları yakalayan basit bir Regex
    # Örn: İYİ PARTİ GRUBU ADINA ERHAN USTA (Samsun) – 
    lines = full_text.split('\n')
    
    speeches = []
    current_speaker = None
    current_text = []
    
    # Regex: Büyük harflerle isim (ve isteğe bağlı parantez) ardından tire
    speaker_pattern = re.compile(r'^([A-ZÇĞİÖŞÜ\s]+(?:\([^)]+\))?)\s*[–-]\s*(.*)')
    
    for line in lines:
        match = speaker_pattern.match(line)
        if match:
            # Önceki konuşmacıyı kaydet
            if current_speaker:
                speeches.append({"raw_speaker": current_speaker.strip(), "text": " ".join(current_text)})
            
            current_speaker = match.group(1)
            current_text = [match.group(2)]
        else:
            if current_speaker:
                current_text.append(line)
                
    if current_speaker:
        speeches.append({"raw_speaker": current_speaker.strip(), "text": " ".join(current_text)})
        
    print(f"Toplam {len(speeches)} adet konuşma (chunk) ayrıştırıldı.\n")
    
    async with get_async_session() as db:
        # Veritabanındaki tüm vekilleri çek (Eşleştirme için)
        result = await db.execute(select(Speaker))
        all_speakers = result.scalars().all()
        
        # RawDocument oluştur
        raw_doc = RawDocument(
            doc_type=DocumentType.TBMM_TRANSCRIPT.value,
            title="Test Tutanak",
            file_path=TEST_FILE,
            raw_text=full_text,
            content_hash=generate_content_hash(full_text, 0, "2023-06-13"),
            date="2023-06-13"
        )
        db.add(raw_doc)
        await db.flush()
        
        for i, speech in enumerate(speeches):
            raw_name = speech["raw_speaker"]
            norm_raw = normalize_speaker_name(raw_name)
            
            # Vekil eşleştirme algoritması (Basit Substring)
            matched_speaker = None
            for s in all_speakers:
                if len(s.normalized_name) > 4 and s.normalized_name in norm_raw:
                    matched_speaker = s
                    break
                    
            speaker_id = matched_speaker.id if matched_speaker else None
            
            # Statement oluştur
            stmt = Statement(
                text=speech["text"],
                speaker_id=speaker_id,
                raw_document_id=raw_doc.id,
                raw_speaker_name=raw_name,
                date="2023-06-13",
                content_hash=generate_content_hash(speech["text"] + str(i), speaker_id, "2023-06-13")
            )
            db.add(stmt)
            await db.flush()
            
            # Neo4j graf ağına ekle
            await create_speech(
                pg_id=stmt.id,
                content=speech["text"][:150] + "...", 
                date="2023-06-13",
                term_name=TERM_NAME,
                raw_speaker_name=raw_name
            )
            
            if speaker_id:
                await add_made_speech_relation(speaker_id, stmt.id)
                print(f"[EŞLEŞTİ] {raw_name} -> {matched_speaker.name}")
            else:
                print(f"[BİLİNMİYOR] {raw_name}")
                
        await db.commit()
    print("\nVeritabanı aktarımı tamamlandı!")

if __name__ == "__main__":
    asyncio.run(process_pdf())
