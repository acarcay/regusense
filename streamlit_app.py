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

# LangGraph Agent imports
try:
    from agents.graph import create_graph, run_analysis
    from agents.state import create_initial_state, Evidence
    LANGGRAPH_AVAILABLE = True
except ImportError:
    LANGGRAPH_AVAILABLE = False

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
    """Get unique speakers from memory (cached for 1 hour).
    
    Note: Uses internal cache in vector_store, this just sorts the result.
    """
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
    
    tab_manual, tab_live, tab_agent, tab_hitl = st.tabs([
        "📝 Manuel Analiz", 
        "🔴 LIVE MODE", 
        "🤖 Agent Pipeline",
        "🔗 Bağ Onayları"
    ])
    
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
    # TAB 3: Agent Pipeline (LangGraph)
    # =========================================================================
    
    with tab_agent:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #6c5ce7 0%, #a29bfe 100%); 
                    padding: 1rem; border-radius: 8px; color: white; margin-bottom: 1rem;">
            <h3 style="margin: 0;">🤖 LangGraph Agent Pipeline</h3>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">
                Multi-agent sistemi ile gelişmiş çelişki analizi. 
                Watchdog → Archivist → Searcher → Analyst → Editor → Human Approval
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        if not LANGGRAPH_AVAILABLE:
            st.error("❌ LangGraph modülü yüklenemedi. `pip install langgraph` ile yükleyin.")
        else:
            # Agent session state
            if "agent_state" not in st.session_state:
                st.session_state.agent_state = None
                st.session_state.agent_running = False
            
            # Input section
            agent_col1, agent_col2 = st.columns([2, 1])
            
            with agent_col1:
                agent_statement = st.text_area(
                    "📝 Analiz Edilecek Açıklama",
                    height=100,
                    placeholder="Politikacının açıklamasını buraya yapıştırın...",
                    key="agent_statement",
                )
                
                agent_speaker = st.text_input(
                    "👤 Konuşmacı",
                    placeholder="örn: Mehmet Şimşek",
                    key="agent_speaker",
                )
            
            with agent_col2:
                st.markdown("**🔧 Agent Ayarları**")
                
                st.info("""
                **Pipeline:**
                1. 👮 Watchdog (Filter)
                2. 🗄️ Archivist (DB Query)
                3. 🕵️ Searcher (Web)
                4. 🧠 Analyst (LLM)
                5. ✍️ Editor (Format)
                6. ✅ Human Approval
                """)
            
            # Run button
            run_agent_btn = st.button(
                "🚀 Agent Pipeline'ı Çalıştır",
                type="primary",
                use_container_width=True,
                disabled=not agent_statement.strip(),
                key="run_agent_btn",
            )
            
            if run_agent_btn and agent_statement.strip():
                st.session_state.agent_running = True
                
                with st.spinner("🔄 Agent Pipeline çalışıyor..."):
                    try:
                        # Run the agent graph
                        result = run_analysis(
                            statement=agent_statement.strip(),
                            speaker=agent_speaker.strip() if agent_speaker else "",
                        )
                        st.session_state.agent_state = result
                        st.session_state.agent_running = False
                        
                    except Exception as e:
                        st.error(f"❌ Agent hatası: {e}")
                        st.session_state.agent_running = False
            
            # Display results
            if st.session_state.agent_state:
                state = st.session_state.agent_state
                
                st.divider()
                
                # Pipeline progress visualization
                st.subheader("📊 Pipeline Durumu")
                
                nodes = ["Watchdog", "Archivist", "Searcher", "Analyst", "Editor", "Approval"]
                node_icons = ["👮", "🗄️", "🕵️", "🧠", "✍️", "✅"]
                
                cols = st.columns(6)
                for i, (node, icon) in enumerate(zip(nodes, node_icons)):
                    with cols[i]:
                        # Determine node status
                        if node == "Watchdog":
                            status = "✅" if state.get("is_newsworthy") is not None else "⏳"
                            value = f"{state.get('newsworthy_score', 0)}/100"
                        elif node == "Archivist":
                            evidence_count = len(state.get("evidence_chain", []))
                            status = "✅" if evidence_count > 0 else "⚠️"
                            value = f"{evidence_count} kanıt"
                        elif node == "Searcher":
                            depth = state.get("search_depth", 0)
                            status = "✅" if depth > 0 else "⏭️"
                            value = f"Derinlik: {depth}"
                        elif node == "Analyst":
                            score = state.get("contradiction_score", None)
                            status = "✅" if score is not None else "⏳"
                            value = f"{score}/10" if score else "-"
                        elif node == "Editor":
                            report = state.get("final_report")
                            status = "✅" if report else "⏳"
                            value = "Hazır" if report else "-"
                        else:  # Approval
                            decision = state.get("human_decision")
                            status = "✅" if decision == "approved" else ("❌" if decision == "rejected" else "⏳")
                            value = decision or "Bekliyor"
                        
                        st.metric(
                            label=f"{icon} {node}",
                            value=value,
                            delta=status,
                        )
                
                st.divider()
                
                # Main results
                result_col1, result_col2 = st.columns([1, 1])
                
                with result_col1:
                    st.subheader("📈 Analiz Sonucu")
                    
                    score = state.get("contradiction_score") or 0
                    ctype = state.get("contradiction_type", "NONE")
                    
                    # Score display
                    score_color = "#e74c3c" if score >= 7 else ("#f39c12" if score >= 4 else "#27ae60")
                    st.markdown(f"""
                    <div style="background: {score_color}; color: white; padding: 2rem; 
                                border-radius: 12px; text-align: center; margin-bottom: 1rem;">
                        <div style="font-size: 4rem; font-weight: bold;">{score}/10</div>
                        <div style="font-size: 1.2rem; opacity: 0.9;">Çelişki Puanı</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Type badge
                    type_labels = {
                        "REVERSAL": "🔄 Tam Tersine Dönüş",
                        "BROKEN_PROMISE": "💔 Kırık Söz",
                        "INCONSISTENCY": "⚠️ Tutarsızlık",
                        "PERSONA_SHIFT": "🎭 Persona Değişimi",
                        "NONE": "✅ Çelişki Yok",
                    }
                    st.info(f"**Tür:** {type_labels.get(ctype, ctype)}")
                    
                    # Explanation
                    explanation = state.get("explanation", "")
                    if explanation:
                        st.warning(f"**💡 Açıklama:** {explanation}")
                    
                    # Key conflict points
                    conflict_points = state.get("key_conflict_points", [])
                    if conflict_points:
                        st.error("**🎯 Çelişki Noktaları:**")
                        for point in conflict_points:
                            st.write(f"• {point}")
                
                with result_col2:
                    st.subheader("📄 Çıktılar")
                    
                    # Final report
                    report = state.get("final_report", "")
                    if report:
                        with st.expander("📋 Rapor", expanded=True):
                            st.markdown(report)
                    
                    # Tweet
                    tweet = state.get("tweet_text", "")
                    if tweet:
                        with st.expander("🐦 Tweet"):
                            st.code(tweet, language=None)
                            st.caption(f"{len(tweet)}/280 karakter")
                    
                    # Video script
                    video = state.get("video_script", "")
                    if video:
                        with st.expander("🎬 Video Script"):
                            st.markdown(video)
                
                # Evidence chain
                evidence_chain = state.get("evidence_chain", [])
                if evidence_chain:
                    st.divider()
                    st.subheader(f"📚 Kanıt Zinciri ({len(evidence_chain)} adet)")
                    
                    for i, ev in enumerate(evidence_chain, 1):
                        if hasattr(ev, 'to_dict'):
                            ev = ev.to_dict()
                        
                        source_type = ev.get("source_type", "UNKNOWN")
                        date = ev.get("date", "Tarih bilinmiyor")
                        content = ev.get("content", "")[:300]
                        
                        with st.expander(f"Kanıt {i} | {source_type} | {date}"):
                            st.write(f'"{content}..."')
                            if ev.get("url"):
                                st.markdown(f"[🔗 Kaynak]({ev['url']})")
                
                # Human approval section (if pending)
                if state.get("pending_approval") and not state.get("human_decision"):
                    st.divider()
                    st.subheader("✅ Onay Bekliyor")
                    
                    st.warning("Bu analiz yayınlanmadan önce onayınızı bekliyor.")
                    
                    approval_col1, approval_col2 = st.columns(2)
                    with approval_col1:
                        if st.button("✅ Onayla", type="primary", use_container_width=True):
                            st.session_state.agent_state["human_decision"] = "approved"
                            st.success("✅ Onaylandı!")
                            st.rerun()
                    
                    with approval_col2:
                        if st.button("❌ Reddet", use_container_width=True):
                            st.session_state.agent_state["human_decision"] = "rejected"
                            st.error("❌ Reddedildi")
                            st.rerun()
    
    # =========================================================================
    # TAB 4: HITL Connection Approvals
    # =========================================================================
    
    with tab_hitl:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%); 
                    padding: 1rem; border-radius: 8px; color: white; margin-bottom: 1rem;">
            <h3 style="margin: 0;">🔗 Bağ Onay Paneli</h3>
            <p style="margin: 0.5rem 0 0 0; opacity: 0.9;">
                Hunter Mode tarafından tespit edilen şüpheli siyasetçi-şirket bağları.
                Her bağı incele ve onayla/reddet.
            </p>
        </div>
        """, unsafe_allow_html=True)
        
        # Check if Neo4j is available
        try:
            import asyncio
            from database import neo4j_client
            
            async def get_pending_connections():
                cypher = """
                MATCH (pc:PendingConnection)
                WHERE pc.status = 'PENDING'
                RETURN pc.speaker_id as speaker_id,
                       pc.speaker_name as speaker_name,
                       pc.company_mersis as company_mersis,
                       pc.company_name as company_name,
                       pc.evidence_count as evidence_count,
                       pc.connection_type as connection_type
                ORDER BY pc.evidence_count DESC
                LIMIT 50
                """
                return await neo4j_client.run_query(cypher)
            
            async def update_connection_status(speaker_id, company_mersis, status, conn_type=None):
                cypher = """
                MATCH (pc:PendingConnection {speaker_id: $speaker_id, company_mersis: $mersis})
                SET pc.status = $status,
                    pc.reviewed_at = datetime()
                """
                if conn_type:
                    cypher += ", pc.connection_type = $conn_type"
                await neo4j_client.run_write(cypher, {
                    "speaker_id": speaker_id,
                    "mersis": company_mersis,
                    "status": status,
                    "conn_type": conn_type,
                })
                
                # If approved, create actual CONNECTED_TO relationship
                if status == "APPROVED" and conn_type:
                    create_cypher = """
                    MATCH (p:Politician {pg_id: $speaker_id})
                    MATCH (o:Organization {mersis_no: $mersis})
                    MERGE (p)-[r:CONNECTED_TO]->(o)
                    SET r.type = $conn_type,
                        r.weight = CASE $conn_type
                            WHEN 'shareholder' THEN 0.8
                            WHEN 'board_member' THEN 0.9
                            WHEN 'former_partner' THEN 0.6
                            ELSE 0.5
                        END,
                        r.source = 'HITL_VERIFIED',
                        r.last_verified = date()
                    """
                    await neo4j_client.run_write(create_cypher, {
                        "speaker_id": speaker_id,
                        "mersis": company_mersis,
                        "conn_type": conn_type,
                    })
            
            # Get pending connections
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            pending = loop.run_until_complete(get_pending_connections())
            
            if not pending:
                st.info("🎉 Bekleyen bağ onayı yok! Hunter Mode çalıştırarak yeni bağlar tespit edin.")
                st.code("python scripts/hunter_scan.py", language="bash")
            else:
                st.success(f"📋 {len(pending)} adet bekleyen bağ onayı")
                
                for i, conn in enumerate(pending):
                    speaker_name = conn.get("speaker_name", "Bilinmiyor")
                    company_name = conn.get("company_name", "Bilinmiyor")
                    evidence_count = conn.get("evidence_count", 0)
                    speaker_id = conn.get("speaker_id")
                    company_mersis = conn.get("company_mersis")
                    
                    # Color based on evidence count
                    if evidence_count >= 10:
                        border_color = "#e74c3c"  # Red - high
                        badge = "🔴 Yüksek"
                    elif evidence_count >= 5:
                        border_color = "#f39c12"  # Orange - medium
                        badge = "🟠 Orta"
                    else:
                        border_color = "#3498db"  # Blue - low
                        badge = "🔵 Düşük"
                    
                    with st.container():
                        st.markdown(f"""
                        <div style="border-left: 4px solid {border_color}; 
                                    padding: 1rem; margin-bottom: 1rem; 
                                    background: #f8f9fa; border-radius: 0 8px 8px 0; color: #2c3e50;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <strong style="font-size: 1.1rem; color: #2c3e50;">👤 {speaker_name}</strong>
                                    <span style="opacity: 0.6; color: #2c3e50;"> → </span>
                                    <strong style="font-size: 1.1rem; color: #2c3e50;">🏢 {company_name}</strong>
                                </div>
                                <span style="background: {border_color}; color: white; 
                                            padding: 0.25rem 0.75rem; border-radius: 12px; font-size: 0.8rem;">
                                    {badge} ({evidence_count} mention)
                                </span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
                        
                        with col1:
                            conn_type = st.selectbox(
                                "Bağ Tipi",
                                ["shareholder", "board_member", "former_partner", "advisor", "unknown"],
                                key=f"conn_type_{i}",
                                format_func=lambda x: {
                                    "shareholder": "💰 Hissedar",
                                    "board_member": "🪑 Yönetim Kurulu",
                                    "former_partner": "🤝 Eski Ortak",
                                    "advisor": "📋 Danışman",
                                    "unknown": "❓ Bilinmiyor",
                                }.get(x, x),
                            )
                        
                        with col2:
                            if st.button("✅ Onayla", key=f"approve_{i}", type="primary"):
                                loop.run_until_complete(
                                    update_connection_status(speaker_id, company_mersis, "APPROVED", conn_type)
                                )
                                st.success("Onaylandı!")
                                st.rerun()
                        
                        with col3:
                            if st.button("❌ Reddet", key=f"reject_{i}"):
                                loop.run_until_complete(
                                    update_connection_status(speaker_id, company_mersis, "REJECTED")
                                )
                                st.warning("Reddedildi")
                                st.rerun()
                        
                        with col4:
                            if st.button("⏭️ Atla", key=f"skip_{i}"):
                                loop.run_until_complete(
                                    update_connection_status(speaker_id, company_mersis, "SKIPPED")
                                )
                                st.rerun()
                        
                        with st.expander("🔍 Kanıtları Gör (Örnek Beyanatlar)"):
                            # Reset Neo4j driver to handle Streamlit loop changes
                            loop.run_until_complete(neo4j_client.close_driver())
                            
                            ev_limit = 5
                            evidence_list = loop.run_until_complete(
                                neo4j_client.get_pending_connection_evidence(speaker_id, company_mersis, ev_limit)
                            )
                            if evidence_list:
                                for ev in evidence_list:
                                    st.markdown(f"**🗓 {ev.get('date')}**")
                                    st.markdown(f"> \"{ev.get('text')}\"")
                                    st.caption(f"ID: {ev.get('pg_id')} | Eşleşen Kelime: `{ev.get('keyword')}`")
                                    st.markdown("---")
                            else:
                                st.info("Kanıt bulunamadı.")
                        
                        st.divider()
                        
        except ImportError as e:
            st.error(f"Neo4j client yüklenemedi: {e}")
        except Exception as e:
            st.warning(f"Neo4j bağlantısı kurulamadı: {e}")
            st.info("Neo4j container'ı çalıştırın: `docker compose up -d neo4j`")
    
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
