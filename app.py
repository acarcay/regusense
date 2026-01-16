"""
ReguSense-Politics: Streamlit Dashboard

Professional Political Intelligence Dashboard for contradiction detection.

Usage:
    streamlit run app.py

Author: ReguSense Team
"""

import streamlit as st
import sys
import os
from pathlib import Path
from datetime import datetime
import subprocess
import platform

# Disable tokenizers parallelism to avoid fork warnings with Streamlit
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Load environment variables from .env file BEFORE any other imports
from dotenv import load_dotenv
load_dotenv()

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from memory.vector_store import PoliticalMemory
from intelligence.gemini_analyzer import GeminiAnalyst
from intelligence.contradiction_engine import ContradictionDetector
from thefuzz import process as fuzz_process

# =========================================================================
# Page Configuration
# =========================================================================

st.set_page_config(
    page_title="ReguSense-Politics",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =========================================================================
# Custom CSS
# =========================================================================

st.markdown("""
<style>
    /* Main container */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Score card styling */
    .score-card {
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        margin-bottom: 1rem;
    }
    
    .score-high {
        background: linear-gradient(135deg, #ff4b4b 0%, #ff6b6b 100%);
        color: white;
    }
    
    .score-medium {
        background: linear-gradient(135deg, #ffa726 0%, #ffb74d 100%);
        color: white;
    }
    
    .score-low {
        background: linear-gradient(135deg, #66bb6a 0%, #81c784 100%);
        color: white;
    }
    
    .score-number {
        font-size: 4rem;
        font-weight: 700;
        line-height: 1;
        margin-bottom: 0.5rem;
    }
    
    .score-label {
        font-size: 1rem;
        opacity: 0.9;
    }
    
    /* Evidence card */
    .evidence-card {
        background: #f8f9fa;
        border-left: 4px solid #6c757d;
        padding: 1rem;
        margin-bottom: 0.5rem;
        border-radius: 0 8px 8px 0;
    }
    
    .source-badge {
        background: #e9ecef;
        padding: 0.25rem 0.5rem;
        border-radius: 4px;
        font-size: 0.75rem;
        color: #495057;
        display: inline-block;
        margin-top: 0.5rem;
    }
    
    /* Header styling */
    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        text-align: center;
    }
    
    /* Type badge */
    .type-badge {
        padding: 0.5rem 1rem;
        border-radius: 20px;
        font-weight: 600;
        display: inline-block;
    }
    
    .type-reversal { background: #dc3545; color: white; }
    .type-broken_promise { background: #fd7e14; color: white; }
    .type-inconsistency { background: #ffc107; color: black; }
    .type-persona_shift { background: #9b59b6; color: white; }
    .type-none { background: #28a745; color: white; }
    
    /* Source type badges - color coded */
    .source-type-badge {
        padding: 0.3rem 0.6rem;
        border-radius: 12px;
        font-size: 0.7rem;
        font-weight: 600;
        display: inline-block;
        margin-right: 0.5rem;
    }
    
    .source-commission { background: #27ae60; color: white; }
    .source-general_assembly { background: #3498db; color: white; }
    .source-social_media { background: #9b59b6; color: white; }
    .source-tv_interview { background: #e67e22; color: white; }
    .source-unknown { background: #95a5a6; color: white; }
    
    /* Citation styling */
    .citation-box {
        background: #f1f3f5;
        border: 1px solid #dee2e6;
        border-radius: 6px;
        padding: 0.5rem;
        font-size: 0.75rem;
        margin-top: 0.5rem;
        font-family: monospace;
    }
</style>
""", unsafe_allow_html=True)


# =========================================================================
# Session State Initialization
# =========================================================================

@st.cache_resource
def load_memory():
    """Load PoliticalMemory (cached)."""
    return PoliticalMemory()


@st.cache_resource
def load_analyzer():
    """Load GeminiAnalyst (cached)."""
    return GeminiAnalyst()


@st.cache_data(ttl=3600)
def get_speakers():
    \"\"\"Get unique speakers from memory (cached for 1 hour).
    
    Note: Uses internal cache in vector_store, this just sorts the result.
    \"\"\"
    memory = load_memory()
    return sorted(list(memory.get_unique_speakers()))


def get_detector(memory, analyzer):
    """Get ContradictionDetector."""
    return ContradictionDetector(memory, analyzer)


def fuzzy_search_speakers(query: str, speakers: list, limit: int = 10) -> list:
    """Fuzzy search speakers by name."""
    if not query or not speakers:
        return speakers[:limit]
    
    results = fuzz_process.extract(query, speakers, limit=limit)
    return [r[0] for r in results if r[1] > 40]


def open_pdf(filepath: str, page: int = 1):
    """Open PDF at specific page (macOS/Linux/Windows)."""
    path = Path(filepath)
    if not path.exists():
        st.error(f"Dosya bulunamadı: {filepath}")
        return
    
    system = platform.system()
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            subprocess.run(["start", "", str(path)], shell=True, check=True)
        else:  # Linux
            subprocess.run(["xdg-open", str(path)], check=True)
    except Exception as e:
        st.error(f"PDF açılamadı: {e}")


# =========================================================================
# Main App
# =========================================================================

def main():
    # Load resources
    try:
        memory = load_memory()
        analyzer = load_analyzer()
        speakers = get_speakers()
        detector = get_detector(memory, analyzer)
    except Exception as e:
        st.error(f"Sistem başlatılamadı: {e}")
        st.stop()
    
    # =========================================================================
    # Header
    # =========================================================================
    
    st.markdown("""
    <div class="main-header">
        <h1>🏛️ ReguSense-Politics</h1>
        <p style="margin: 0; opacity: 0.8;">Siyasi Çelişki Tespit Sistemi | Political Contradiction Detection</p>
    </div>
    """, unsafe_allow_html=True)
    
    # =========================================================================
    # Sidebar - Speaker Selection
    # =========================================================================
    
    with st.sidebar:
        st.header("🎯 Analiz Ayarları")
        
        # Speaker search
        st.subheader("👤 Konuşmacı Seçimi")
        
        speaker_search = st.text_input(
            "İsim ara...",
            placeholder="örn: Mahinur, Şimşek, Cevdet",
            key="speaker_search",
        )
        
        # Filter speakers based on search
        if speaker_search:
            filtered_speakers = fuzzy_search_speakers(speaker_search, speakers)
        else:
            filtered_speakers = speakers[:20]  # Show first 20 by default
        
        selected_speaker = st.selectbox(
            "Konuşmacı",
            options=[""] + filtered_speakers,
            format_func=lambda x: "Tümü" if x == "" else x[:50] + ("..." if len(x) > 50 else ""),
            key="speaker_select",
        )
        
        st.divider()
        
        # Source Type Filter
        st.subheader("📂 Kaynak Tipi")
        source_types = [
            "",
            "TBMM_COMMISSION",
            "TBMM_GENERAL_ASSEMBLY",
            "SOCIAL_MEDIA",
            "TV_INTERVIEW",
        ]
        source_labels = {
            "": "Tümü",
            "TBMM_COMMISSION": "🏛️ TBMM Komisyon",
            "TBMM_GENERAL_ASSEMBLY": "🎤 TBMM Genel Kurul",
            "SOCIAL_MEDIA": "📱 Sosyal Medya (X)",
            "TV_INTERVIEW": "📺 TV Röportajı",
        }
        selected_source_type = st.selectbox(
            "Kaynak Tipi",
            options=source_types,
            format_func=lambda x: source_labels.get(x, x),
            key="source_type_select",
        )
        
        st.divider()
        
        # Stats
        st.subheader("📊 Veritabanı")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Toplam Kayıt", f"{memory.count():,}")
        with col2:
            st.metric("Konuşmacı", len(speakers))
        
        st.divider()
        
        # Analysis settings
        st.subheader("⚙️ Ayarlar")
        top_k = st.slider("Tarihsel Eşleşme Sayısı", 3, 10, 5)
        threshold = st.slider("Çelişki Eşiği", 50, 90, 70)
    
    # =========================================================================
    # Main Content - Tabbed Interface
    # =========================================================================
    
    tab_manual, tab_live = st.tabs(["📝 Manuel Analiz", "🔴 LIVE MODE"])
    
    # =========================================================================
    # TAB 1: Manual Analysis (Original)
    # =========================================================================
    
    with tab_manual:
        col_input, col_result = st.columns([1, 1])
        
        with col_input:
            st.subheader("📝 Yeni Açıklama")
            
            new_statement = st.text_area(
                "Analiz edilecek açıklama",
                height=150,
                placeholder="Politikacının yeni açıklamasını buraya yapıştırın...\n\nÖrnek: 'Enflasyon tek haneye düşecek'",
                key="new_statement",
            )
            
            analyze_btn = st.button(
                "🔍 Çelişkileri Analiz Et",
                type="primary",
                use_container_width=True,
                disabled=not new_statement.strip(),
            )
    
    # =========================================================================
    # TAB 2: Live Mode
    # =========================================================================
    
    with tab_live:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #c0392b 0%, #e74c3c 100%); 
                    padding: 1rem; border-radius: 8px; color: white; margin-bottom: 1rem;">
            <h3 style="margin: 0;">🔴 CANLI YAYIN ANALİZİ</h3>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">
                YouTube canlı yayınlarını veya video kayıtlarını gerçek zamanlı olarak analiz edin.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Live Mode Status
        live_col1, live_col2 = st.columns([2, 1])
        
        with live_col1:
            youtube_url = st.text_input(
                "🎬 YouTube URL",
                placeholder="https://www.youtube.com/watch?v=...",
                key="youtube_url",
            )
            
            live_speaker = st.text_input(
                "👤 Konuşmacı (opsiyonel)",
                placeholder="Otomatik tespit edilecek",
                key="live_speaker",
            )
        
        with live_col2:
            st.markdown("**Whisper Modeli**")
            whisper_model = st.selectbox(
                "Model",
                ["tiny", "base", "small", "medium"],
                index=1,  # Default: base
                key="whisper_model",
                label_visibility="collapsed",
            )
            
            st.caption("""
            - **tiny**: Hızlı, düşük doğruluk
            - **base**: Dengeli ⭐
            - **small**: Daha doğru
            - **medium**: Yavaş, yüksek doğruluk
            """)
        
        # Start/Stop buttons
        btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 2])
        
        with btn_col1:
            start_live = st.button(
                "▶️ Başlat",
                type="primary",
                use_container_width=True,
                disabled=not youtube_url.strip(),
            )
        
        with btn_col2:
            stop_live = st.button(
                "⏹️ Durdur",
                use_container_width=True,
            )
        
        # Initialize live session state
        if "live_active" not in st.session_state:
            st.session_state.live_active = False
            st.session_state.live_transcripts = []
            st.session_state.live_alerts = []
        
        # Handle start/stop
        if start_live and youtube_url.strip():
            st.session_state.live_active = True
            st.session_state.live_transcripts = []
            st.session_state.live_alerts = []
            
            # Import live engine
            try:
                from intelligence.live_engine import LiveProcessor
                
                with st.spinner("🔄 YouTube videosu indiriliyor ve işleniyor... (Bu birkaç dakika sürebilir)"):
                    processor = LiveProcessor(whisper_model=whisper_model, chunk_duration=30)
                    
                    # Process video
                    speaker = live_speaker.strip() if live_speaker.strip() else None
                    
                    progress_bar = st.progress(0, text="Video indiriliyor...")
                    
                    chunk_count = 0
                    for chunk in processor.stream_youtube(youtube_url, speaker=speaker or ""):
                        chunk_count += 1
                        
                        # Add to transcripts
                        st.session_state.live_transcripts.append({
                            "timestamp": chunk.timestamp.strftime("%H:%M:%S"),
                            "text": chunk.text,
                            "speaker": chunk.speaker,
                        })
                        
                        progress_bar.progress(min(chunk_count * 10, 100), text=f"Chunk {chunk_count} işlendi...")
                        
                        # Run contradiction detection every 2 chunks
                        if chunk_count % 2 == 0 and chunk.text.strip():
                            try:
                                result = detector.detect(
                                    new_statement=chunk.text,
                                    speaker=speaker or selected_speaker,
                                    filter_by_speaker=bool(speaker or selected_speaker),
                                )
                                
                                if result.is_contradiction and result.contradiction_score >= 75:
                                    st.session_state.live_alerts.append({
                                        "score": result.contradiction_score,
                                        "type": result.contradiction_type.value,
                                        "text": chunk.text,
                                        "explanation": result.explanation,
                                        "key_conflict_points": result.key_conflict_points,
                                        "historical_matches": result.historical_matches[:2],  # Top 2 for context
                                    })
                            except Exception as e:
                                pass  # Continue even if detection fails
                    
                    progress_bar.progress(100, text="✅ Video işlendi!")
                    st.success(f"✅ {chunk_count} segment işlendi!")
                    
            except ImportError as e:
                st.error(f"❌ Live Engine yüklenemedi: {e}")
            except Exception as e:
                st.error(f"❌ İşleme hatası: {e}")
        
        if stop_live:
            st.session_state.live_active = False
            st.success("⏹️ Canlı analiz durduruldu.")
        
        # Live Transcript Display
        st.divider()
        st.subheader("📃 Canlı Transkript")
        
        transcript_container = st.container(height=300)
        
        with transcript_container:
            if st.session_state.live_transcripts:
                for i, entry in enumerate(st.session_state.live_transcripts[-20:]):  # Last 20
                    ts = entry.get("timestamp", "")
                    text = entry.get("text", "")
                    st.text(f"[{ts}] {text}")
            else:
                st.info("Transkript burada görünecek...")
        
        # Live Alerts Display
        if st.session_state.live_alerts:
            st.divider()
            st.subheader("🚨 ÇELİŞKİ ALARMLARI")
            
            for idx, alert in enumerate(st.session_state.live_alerts[-5:]):  # Last 5 alerts
                score = alert.get("score", 0)
                alert_type = alert.get("type", "UNKNOWN")
                text = alert.get("text", "")
                explanation = alert.get("explanation", "")
                key_points = alert.get("key_conflict_points", [])
                historical = alert.get("historical_matches", [])
                
                if score >= 75:
                    alert_color = "#c0392b"  # Red
                    alert_icon = "🔴"
                    border_color = "#a93226"
                else:
                    alert_color = "#e67e22"  # Orange
                    alert_icon = "🟠"
                    border_color = "#d35400"
                
                # Type labels in Turkish
                type_labels = {
                    "REVERSAL": "🔄 TAM TERSİNE DÖNÜŞ",
                    "BROKEN_PROMISE": "💔 KIRIK SÖZ",
                    "INCONSISTENCY": "⚠️ TUTARSIZLIK",
                    "PERSONA_SHIFT": "🎭 PERSONA DEĞİŞİMİ",
                    "NONE": "✅ TUTARLI",
                }
                type_label = type_labels.get(alert_type, alert_type)
                
                # Build key points HTML if available
                key_points_html = ""
                if key_points:
                    points_list = "".join([f"<li style='margin: 0.25rem 0;'>{point}</li>" for point in key_points])
                    key_points_html = f"""
                    <div style="background: rgba(0,0,0,0.2); padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem;">
                        <strong>🎯 Çelişki Noktaları:</strong>
                        <ul style="margin: 0.5rem 0 0 1rem; padding: 0;">{points_list}</ul>
                    </div>
                    """
                
                # Build historical evidence HTML
                historical_html = ""
                if historical:
                    hist_items = ""
                    for h in historical[:2]:
                        h_text = h.get("text", "")[:200] + "..." if len(h.get("text", "")) > 200 else h.get("text", "")
                        h_date = h.get("date", "Tarih bilinmiyor")
                        h_source = h.get("source_type", "UNKNOWN")
                        source_labels = {
                            "TBMM_COMMISSION": "🏛️ Komisyon",
                            "TBMM_GENERAL_ASSEMBLY": "🎤 Genel Kurul",
                            "SOCIAL_MEDIA": "📱 Sosyal Medya",
                            "TV_INTERVIEW": "📺 TV",
                        }
                        source_label = source_labels.get(h_source, "📄 Diğer")
                        hist_items += f"""
                        <div style="background: rgba(255,255,255,0.08); padding: 0.5rem; border-radius: 4px; margin-top: 0.5rem;">
                            <span style="font-size: 0.75rem; opacity: 0.8;">{source_label} | {h_date}</span>
                            <p style="margin: 0.25rem 0 0 0; font-size: 0.9rem;">"{h_text}"</p>
                        </div>
                        """
                    historical_html = f"""
                    <div style="background: rgba(0,0,0,0.25); padding: 0.75rem; border-radius: 6px; margin-top: 0.75rem;">
                        <strong>📚 Çelişen Geçmiş Açıklamalar:</strong>
                        {hist_items}
                    </div>
                    """
                
                # Build explanation HTML
                explanation_html = ""
                if explanation:
                    explanation_html = f"""
                    <div style="background: rgba(255,255,255,0.1); padding: 0.75rem; border-radius: 6px;">
                        <strong>💡 AI Açıklaması:</strong>
                        <p style="margin: 0.5rem 0 0 0;">{explanation}</p>
                    </div>
                    """
                
                # Truncate text for display
                display_text = text[:300] + "..." if len(text) > 300 else text
                
                # Build complete HTML
                alert_html = f"""
                <div style="background: linear-gradient(135deg, {alert_color} 0%, {border_color} 100%); 
                            color: white; padding: 1.25rem; border-radius: 12px; margin-bottom: 1rem;
                            box-shadow: 0 4px 15px rgba(0,0,0,0.2);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                        <h4 style="margin: 0; font-size: 1.2rem;">{alert_icon} ÇELİŞKİ TESPİT EDİLDİ</h4>
                        <span style="background: rgba(255,255,255,0.2); padding: 0.4rem 0.8rem; border-radius: 20px; font-weight: bold;">
                            Skor: {score}/100
                        </span>
                    </div>
                    
                    <div style="margin-bottom: 0.75rem;">
                        <span style="background: rgba(255,255,255,0.15); padding: 0.3rem 0.6rem; border-radius: 6px; font-size: 0.85rem;">
                            {type_label}
                        </span>
                    </div>
                    
                    <div style="background: rgba(0,0,0,0.15); padding: 0.75rem; border-radius: 6px; margin-bottom: 0.75rem;">
                        <strong>📝 Yeni Açıklama:</strong>
                        <p style="margin: 0.5rem 0 0 0; font-style: italic; opacity: 0.95;">"{display_text}"</p>
                    </div>
                    
                    {explanation_html}
                    
                    {key_points_html}
                    
                    {historical_html}
                </div>
                """
                
                st.markdown(alert_html, unsafe_allow_html=True)
    
    # =========================================================================
    # Analysis Result (inside Manual tab)
    # =========================================================================
    
    with tab_manual:
        with col_result:
            st.subheader("📊 Analiz Sonucu")
            
            if analyze_btn and new_statement.strip():
                with st.spinner("Analiz yapılıyor..."):
                    # Update detector settings
                    detector.top_k = top_k
                    detector.contradiction_threshold = threshold
                    
                    # Run analysis
                    result = detector.detect(
                        new_statement=new_statement.strip(),
                        speaker=selected_speaker,
                        filter_by_speaker=bool(selected_speaker),
                    )
                
                # Display score
                score = result.contradiction_score
                score_class = "high" if score >= 70 else ("medium" if score >= 40 else "low")
                verdict_text = "ÇELİŞKİ TESPİT EDİLDİ" if result.is_contradiction else "TUTARLI"
                
                st.markdown(f"""
                <div class="score-card score-{score_class}">
                    <div class="score-number">{score}</div>
                    <div class="score-label">{verdict_text}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Type badge
                type_class = result.contradiction_type.value.lower()
                type_labels = {
                    "REVERSAL": "🔄 TAM TERSİNE DÖNÜŞ",
                    "BROKEN_PROMISE": "💔 KIRIK SÖZ",
                    "INCONSISTENCY": "⚠️ TUTARSIZLIK",
                    "PERSONA_SHIFT": "🎭 PERSONA DEĞİŞİMİ",
                    "NONE": "✅ TUTARLI",
                }
                type_label = type_labels.get(result.contradiction_type.value, result.contradiction_type.value)
                
                st.markdown(f"""
                <div style="text-align: center; margin-bottom: 1rem;">
                    <span class="type-badge type-{type_class}">{type_label}</span>
                </div>
                """, unsafe_allow_html=True)
                
                # Explanation
                if result.explanation:
                    st.info(f"💡 **Açıklama:** {result.explanation}")
                
                # Conflict points
                if result.key_conflict_points:
                    st.warning("**🎯 Çelişki Noktaları:**")
                    for point in result.key_conflict_points:
                        st.write(f"• {point}")
                
                # Store result in session
                st.session_state["last_result"] = result
            
            elif "last_result" not in st.session_state:
                st.info("👆 Yeni bir açıklama girin ve analiz butonuna tıklayın.")
    
    # =========================================================================
    # Historical Evidence Section
    # =========================================================================
    
    if "last_result" in st.session_state and st.session_state.last_result.historical_matches:
        st.divider()
        st.subheader("📚 Tarihsel Kanıtlar")
        
        result = st.session_state.last_result
        
        for i, match in enumerate(result.historical_matches, 1):
            # Determine source type and badge class
            source_type = match.get("source_type", "UNKNOWN")
            badge_class_map = {
                "TBMM_COMMISSION": ("source-commission", "🟢 Komisyon"),
                "TBMM_GENERAL_ASSEMBLY": ("source-general_assembly", "🔵 Genel Kurul"),
                "SOCIAL_MEDIA": ("source-social_media", "🟣 Sosyal Medya"),
                "TV_INTERVIEW": ("source-tv_interview", "🟠 TV Röportaj"),
            }
            badge_class, badge_label = badge_class_map.get(source_type, ("source-unknown", "⚪ Diğer"))
            
            with st.expander(
                f"📄 Kanıt {i} | {match.get('date', 'Tarih bilinmiyor')} | {badge_label} | Benzerlik: {match.get('similarity', 0):.1%}",
                expanded=(i == 1),
            ):
                # Source type badge at top
                st.markdown(f"""
                <div class="source-type-badge {badge_class}">{badge_label}</div>
                """, unsafe_allow_html=True)
                
                # Statement text
                st.markdown(f"**Açıklama:**")
                st.write(f'"{match.get("text", "")}"')
                
                # Citation box
                source = match.get("source", "Bilinmiyor")
                page = match.get("page_number", 0)
                date = match.get("date", "Tarih bilinmiyor")
                
                st.markdown(f"""
                <div class="citation-box">
                    📁 <strong>Kaynak:</strong> {source}<br>
                    📄 <strong>Sayfa:</strong> {page if page > 0 else "N/A"}<br>
                    📅 <strong>Tarih:</strong> {date}<br>
                    🏷️ <strong>Tip:</strong> {source_type}
                </div>
                """, unsafe_allow_html=True)
                
                # Open PDF button
                source_file = match.get("source", "")
                if source_file and source_file.endswith(".pdf"):
                    col_a, col_b = st.columns([3, 1])
                    with col_b:
                        pdf_paths = [
                            Path("data/raw/contracts") / source_file,
                            Path("data/organized") / source_file,
                        ]
                        
                        for pdf_path in pdf_paths:
                            if pdf_path.exists():
                                if st.button(f"📂 PDF Aç", key=f"open_pdf_{i}"):
                                    open_pdf(str(pdf_path), page=page)
                                break
    
    # =========================================================================
    # Footer
    # =========================================================================
    
    st.divider()
    st.caption(
        f"ReguSense-Politics v1.0 | "
        f"Son güncelleme: {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
        f"Veritabanı: {memory.count():,} kayıt"
    )


if __name__ == "__main__":
    main()
