#!/usr/bin/env python3
"""
Dry-Run Deduplication Analysis for ReguSense.

Analyzes the existing ChromaDB data to determine:
1. Total record count
2. Unique records (after content_hash deduplication)
3. Percentage reduction
4. Sample of duplicates found

This script does NOT modify any data - it's read-only analysis.

Usage:
    python scripts/analyze_dedup.py
"""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings


def normalize_text(text: str) -> str:
    """Normalize text for hash comparison."""
    if not text:
        return ""
    # Lowercase, strip, collapse whitespace
    return re.sub(r'\s+', ' ', text.lower().strip())


def generate_content_hash(text: str, speaker: str, date: str) -> str:
    """Generate SHA-256 hash for content deduplication."""
    normalized_text = normalize_text(text)
    normalized_speaker = speaker.lower().strip() if speaker else ""
    content = f"{normalized_text}|{normalized_speaker}|{date}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def analyze_chromadb(persist_dir: str = "data/chromadb") -> dict:
    """
    Analyze ChromaDB for duplicates.
    
    Returns:
        Dict with analysis results
    """
    print(f"📂 Loading ChromaDB from: {persist_dir}")
    
    # Initialize ChromaDB client
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    
    # Get collection
    try:
        collection = client.get_collection("political_statements")
    except Exception as e:
        print(f"❌ Error: Could not find collection 'political_statements': {e}")
        return {"error": str(e)}
    
    total_count = collection.count()
    print(f"📊 Total records in ChromaDB: {total_count:,}")
    
    if total_count == 0:
        return {"total": 0, "unique": 0, "duplicates": 0}
    
    # Fetch all records in batches
    print("🔄 Fetching records (this may take a while)...")
    
    hash_to_ids = defaultdict(list)
    speaker_counts = defaultdict(int)
    source_type_counts = defaultdict(int)
    
    batch_size = 5000
    offset = 0
    processed = 0
    
    while offset < total_count:
        results = collection.get(
            include=["documents", "metadatas"],
            limit=batch_size,
            offset=offset,
        )
        
        if not results or not results.get("ids"):
            break
        
        for i, doc_id in enumerate(results["ids"]):
            text = results["documents"][i] if results["documents"] else ""
            metadata = results["metadatas"][i] if results["metadatas"] else {}
            
            speaker = metadata.get("speaker", "")
            date = metadata.get("date", "")
            source_type = metadata.get("source_type", "UNKNOWN")
            
            # Generate content hash
            content_hash = generate_content_hash(text, speaker, date)
            hash_to_ids[content_hash].append({
                "id": doc_id,
                "speaker": speaker,
                "date": date,
                "text_preview": text[:100] if text else "",
            })
            
            # Count stats
            speaker_counts[speaker] += 1
            source_type_counts[source_type] += 1
        
        processed += len(results["ids"])
        offset += batch_size
        print(f"   Processed {processed:,}/{total_count:,} records...")
    
    # Calculate duplicates
    unique_count = len(hash_to_ids)
    duplicate_count = total_count - unique_count
    reduction_pct = (duplicate_count / total_count * 100) if total_count > 0 else 0
    
    # Find sample duplicates
    duplicate_samples = []
    for content_hash, entries in hash_to_ids.items():
        if len(entries) > 1:
            duplicate_samples.append({
                "count": len(entries),
                "speaker": entries[0]["speaker"],
                "preview": entries[0]["text_preview"],
            })
            if len(duplicate_samples) >= 10:
                break
    
    # Top speakers
    top_speakers = sorted(speaker_counts.items(), key=lambda x: -x[1])[:10]
    
    return {
        "total": total_count,
        "unique": unique_count,
        "duplicates": duplicate_count,
        "reduction_pct": round(reduction_pct, 2),
        "top_speakers": top_speakers,
        "source_types": dict(source_type_counts),
        "duplicate_samples": duplicate_samples,
    }


def main():
    print("=" * 60)
    print("🔍 ReguSense Deduplication Analysis (Dry-Run)")
    print("=" * 60)
    print()
    
    # Run analysis
    results = analyze_chromadb()
    
    if "error" in results:
        print(f"\n❌ Analysis failed: {results['error']}")
        return
    
    # Print results
    print()
    print("=" * 60)
    print("📈 RESULTS")
    print("=" * 60)
    print(f"  Total Records:     {results['total']:,}")
    print(f"  Unique Records:    {results['unique']:,}")
    print(f"  Duplicates:        {results['duplicates']:,}")
    print(f"  Reduction:         {results['reduction_pct']}%")
    print()
    
    print("📊 Source Types:")
    for source_type, count in results.get("source_types", {}).items():
        print(f"    {source_type}: {count:,}")
    print()
    
    print("👤 Top 10 Speakers:")
    for speaker, count in results.get("top_speakers", []):
        display_name = speaker if speaker else "(Unknown)"
        print(f"    {display_name}: {count:,}")
    print()
    
    if results.get("duplicate_samples"):
        print("🔁 Sample Duplicates:")
        for dup in results["duplicate_samples"][:5]:
            print(f"    [{dup['count']}x] {dup['speaker']}: \"{dup['preview']}...\"")
    print()
    
    # Save results to JSON
    output_path = Path("data/dedup_analysis.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 Results saved to: {output_path}")
    
    # Recommendation
    print()
    print("=" * 60)
    print("💡 RECOMMENDATION")
    print("=" * 60)
    if results["reduction_pct"] > 30:
        print(f"  ⚠️  High duplication detected ({results['reduction_pct']}%)")
        print(f"  Migrating to PostgreSQL will reduce data from {results['total']:,} to {results['unique']:,}")
        print("  This will significantly improve query performance.")
    else:
        print(f"  ✅ Low duplication ({results['reduction_pct']}%)")
        print("  Data is relatively clean.")
    print()


if __name__ == "__main__":
    main()
