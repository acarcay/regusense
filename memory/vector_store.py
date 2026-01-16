"""
Political Memory - Vector Store for Statement Embeddings.

Uses ChromaDB for persistent vector storage and sentence-transformers
for creating multilingual embeddings of political statements.

Author: ReguSense Team
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Disable tokenizers parallelism BEFORE importing sentence_transformers
# This prevents fork warning spam in multi-process environments like Streamlit
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# Module-level speaker cache (cleared on new ingest)
_speaker_cache: Optional[set[str]] = None


@dataclass
class StatementMatch:
    """A matched statement from semantic search.
    
    Attributes:
        text: The statement text
        speaker: Name of the speaker
        date: Date of the statement
        topic: Topic/category of the statement
        source: Source of the statement (filename)
        source_type: Type of source (TBMM_COMMISSION, SOCIAL_MEDIA, TV_INTERVIEW, etc.)
        page_number: Page number in the source document
        similarity: Similarity score (0-1, higher is more similar)
        document_id: Unique ID of the document
    """
    text: str
    speaker: str = ""
    date: str = ""
    topic: str = ""
    source: str = ""
    source_type: str = "UNKNOWN"
    page_number: int = 0
    similarity: float = 0.0
    document_id: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "text": self.text,
            "speaker": self.speaker,
            "date": self.date,
            "topic": self.topic,
            "source": self.source,
            "source_type": self.source_type,
            "page_number": self.page_number,
            "similarity": round(self.similarity, 4),
            "document_id": self.document_id,
        }


class PoliticalMemory:
    """Vector store for political statements using ChromaDB.
    
    Provides semantic search over a database of political statements,
    enabling contradiction detection by finding similar past statements.
    
    Example:
        >>> memory = PoliticalMemory()
        >>> memory.ingest_text(
        ...     "Enflasyon yüzde 70 civarında kalacak",
        ...     {"speaker": "Mehmet Şimşek", "date": "2023-01-15"}
        ... )
        >>> matches = memory.search("Enflasyon tek haneye düşecek")
        >>> print(matches[0].text)
        'Enflasyon yüzde 70 civarında kalacak'
    """
    
    # Multilingual model with good Turkish support
    DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    DEFAULT_COLLECTION = "political_statements"
    DEFAULT_PERSIST_DIR = "data/chromadb"
    
    def __init__(
        self,
        collection_name: str = DEFAULT_COLLECTION,
        persist_dir: str | Path = DEFAULT_PERSIST_DIR,
        model_name: str = DEFAULT_MODEL,
    ):
        """
        Initialize the political memory store.
        
        Args:
            collection_name: Name of the ChromaDB collection
            persist_dir: Directory for persistent storage
            model_name: SentenceTransformer model for embeddings
        """
        self.collection_name = collection_name
        self.persist_dir = Path(persist_dir)
        self.model_name = model_name
        
        # Ensure persist directory exists
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize embedding model
        logger.info(f"Loading embedding model: {model_name}")
        self._model = SentenceTransformer(model_name)
        
        # Initialize ChromaDB client with persistence
        logger.info(f"Initializing ChromaDB at: {self.persist_dir}")
        self._client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        
        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"description": "Political statements for contradiction detection"},
        )
        
        logger.info(
            f"PoliticalMemory initialized. Collection '{collection_name}' has "
            f"{self._collection.count()} documents."
        )
    
    def _generate_id(self) -> str:
        """Generate a unique document ID."""
        return str(uuid.uuid4())
    
    def _create_embedding(self, text: str) -> list[float]:
        """Create embedding for a single text."""
        return self._model.encode(text, convert_to_numpy=True).tolist()
    
    def _create_embeddings_batch(self, texts: list[str]) -> list[list[float]]:
        """Create embeddings for multiple texts in batch (much faster)."""
        if not texts:
            return []
        embeddings = self._model.encode(
            texts, 
            batch_size=64, 
            show_progress_bar=len(texts) > 100,
            convert_to_numpy=True
        )
        return embeddings.tolist()
    
    def ingest_text(
        self,
        text: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> str:
        """
        Ingest a single text into the vector store.
        
        Args:
            text: The statement text to store
            metadata: Optional metadata dict with keys:
                - speaker: Name of the speaker
                - date: Date of the statement (ISO format or any string)
                - topic: Topic/category
                - source: Source of the statement
                
        Returns:
            Document ID of the ingested text
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        doc_id = self._generate_id()
        metadata = metadata or {}
        
        # Normalize metadata
        meta = {
            "speaker": str(metadata.get("speaker", "")),
            "date": str(metadata.get("date", "")),
            "topic": str(metadata.get("topic", "")),
            "source": str(metadata.get("source", "")),
            "source_type": str(metadata.get("source_type", "UNKNOWN")),
            "ingested_at": datetime.now().isoformat(),
        }
        
        # Create embedding and add to collection
        embedding = self._create_embedding(text)
        
        self._collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
        
        logger.debug(f"Ingested document {doc_id}: {text[:50]}...")
        return doc_id
    
    def ingest_batch(
        self,
        items: list[dict[str, Any]],
    ) -> list[str]:
        """
        Ingest multiple texts in batch.
        
        Args:
            items: List of dicts, each containing:
                - text: The statement text (required)
                - speaker: Name of the speaker
                - date: Date of the statement
                - topic: Topic/category
                - source: Source of the statement
                
        Returns:
            List of document IDs
        """
        if not items:
            return []
        
        ids = []
        embeddings = []
        documents = []
        metadatas = []
        
        # First pass: collect texts and metadata
        valid_items = []
        for item in items:
            text = item.get("text", "").strip()
            if not text:
                continue
            valid_items.append((text, item))
        
        if not valid_items:
            return []
        
        # BATCH EMBEDDING - Much faster!
        texts_to_embed = [t[0] for t in valid_items]
        embeddings = self._create_embeddings_batch(texts_to_embed)
        
        # Build final lists
        for i, (text, item) in enumerate(valid_items):
            doc_id = self._generate_id()
            ids.append(doc_id)
            documents.append(text)
            metadatas.append({
                "speaker": str(item.get("speaker", "")),
                "date": str(item.get("date", "")),
                "year": str(item.get("date", ""))[:4] if item.get("date") else "",
                "month": str(item.get("date", ""))[5:7] if len(str(item.get("date", ""))) >= 7 else "",
                "topic": str(item.get("topic", "")),
                "source": str(item.get("source", "")),
                "source_type": str(item.get("source_type", "UNKNOWN")),
                "session_id": str(item.get("session_id", "")),
                "page_number": int(item.get("page", 0)),
                "ingested_at": datetime.now().isoformat(),
            })
        
        if ids:
            self._collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Batch ingested {len(ids)} documents")
            
            # Invalidate speaker cache on new ingest
            global _speaker_cache
            _speaker_cache = None
        
        return ids
    
    def search(
        self,
        query_text: str,
        top_k: int = 5,
        speaker_filter: Optional[str] = None,
        source_type_filter: Optional[str] = None,
        year_filter: Optional[str] = None,
        month_filter: Optional[str] = None,
    ) -> list[StatementMatch]:
        """
        Search for semantically similar statements.
        
        Args:
            query_text: The query text to search for
            top_k: Number of results to return (default: 5)
            speaker_filter: Optional filter by speaker name
            source_type_filter: Optional filter by source type 
                (e.g., "TBMM_COMMISSION", "SOCIAL_MEDIA", "TV_INTERVIEW")
            year_filter: Optional filter by year (e.g., "2024")
            month_filter: Optional filter by month (e.g., "01", "12")
            
        Returns:
            List of StatementMatch objects ordered by similarity (highest first)
        """
        if not query_text or not query_text.strip():
            return []
        
        # Create query embedding
        query_embedding = self._create_embedding(query_text)
        
        # Build where filter
        where_filter = None
        filters = []
        
        if speaker_filter:
            filters.append({"speaker": {"$eq": speaker_filter}})
        
        if source_type_filter:
            filters.append({"source_type": {"$eq": source_type_filter}})
        
        if year_filter:
            filters.append({"year": {"$eq": year_filter}})
        
        if month_filter:
            filters.append({"month": {"$eq": month_filter}})
        
        if len(filters) == 1:
            where_filter = filters[0]
        elif len(filters) > 1:
            where_filter = {"$and": filters}
        
        # Query ChromaDB
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count() or 1),
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
        
        # Convert to StatementMatch objects
        matches = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 0
                doc_id = results["ids"][0][i] if results["ids"] else ""
                
                # Convert distance to similarity (ChromaDB uses L2 distance by default)
                # Lower distance = higher similarity
                similarity = 1 / (1 + distance)
                
                matches.append(StatementMatch(
                    text=doc,
                    speaker=metadata.get("speaker", ""),
                    date=metadata.get("date", ""),
                    topic=metadata.get("topic", ""),
                    source=metadata.get("source", ""),
                    source_type=metadata.get("source_type", "UNKNOWN"),
                    page_number=int(metadata.get("page_number", 0)),
                    similarity=similarity,
                    document_id=doc_id,
                ))
        
        return matches
    
    def count(self) -> int:
        """Return the number of documents in the collection."""
        return self._collection.count()
    
    def clear(self) -> None:
        """Clear all documents from the collection."""
        self._client.delete_collection(self.collection_name)
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"description": "Political statements for contradiction detection"},
        )
        logger.info(f"Cleared collection '{self.collection_name}'")
    
    def get_stats(self) -> dict[str, Any]:
        """Get statistics about the memory store."""
        count = self.count()
        return {
            "collection_name": self.collection_name,
            "document_count": count,
            "persist_dir": str(self.persist_dir),
            "model_name": self.model_name,
        }
    
    def get_unique_speakers(self) -> set[str]:
        """
        Get all unique speaker names from the collection.
        
        Uses sampling and caching for performance (avoids loading 70K+ docs).
        
        Returns:
            Set of unique speaker names found in the database
        """
        global _speaker_cache
        
        # Return cached speakers if available
        if _speaker_cache is not None:
            return _speaker_cache
        
        # Sample-based approach: fetch in chunks to avoid memory explosion
        try:
            speakers = set()
            total_count = self._collection.count()
            
            # For smaller collections, just fetch all
            if total_count <= 5000:
                results = self._collection.get(include=["metadatas"])
                if results and results.get("metadatas"):
                    for metadata in results["metadatas"]:
                        speaker = metadata.get("speaker", "")
                        if speaker and speaker.strip():
                            speakers.add(speaker.strip())
            else:
                # For large collections, sample in chunks
                chunk_size = 5000
                offset = 0
                while offset < total_count and offset < 50000:  # Max 50K docs
                    results = self._collection.get(
                        include=["metadatas"],
                        limit=chunk_size,
                        offset=offset,
                    )
                    if not results or not results.get("metadatas"):
                        break
                    for metadata in results["metadatas"]:
                        speaker = metadata.get("speaker", "")
                        if speaker and speaker.strip():
                            speakers.add(speaker.strip())
                    offset += chunk_size
                    
                    # Early exit if we have enough unique speakers
                    if len(speakers) > 1000:
                        break
            
            logger.info(f"Found {len(speakers)} unique speakers (cached)")
            _speaker_cache = speakers
            return speakers
            
        except Exception as e:
            logger.warning(f"Failed to get unique speakers: {e}")
            return set()
    
    def clear_speaker_cache(self) -> None:
        """Clear the speaker cache (call after manual data changes)."""
        global _speaker_cache
        _speaker_cache = None
        logger.debug("Speaker cache cleared")
