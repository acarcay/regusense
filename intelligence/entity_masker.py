"""
Entity Masker: Pre-processes text to mask known politician names.

This module runs BEFORE Hunter scan to neutralize politician names,
preventing false positives where surnames match company keywords.

Example:
    Input:  "Sayın Cüneyt Yüksel, Yüksel İnşaat hakkında konuştu."
    Output: "Sayın [POLITICIAN_ID_123], Yüksel İnşaat hakkında konuştu."
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class EntityMasker:
    """
    Masks politician names in text using a pre-loaded list.
    
    Key Features:
    - Longest-first sorting: "Mehmet Cengiz" masked before "Cengiz"
    - Case-insensitive matching
    - Title preservation: "Sayın" stays outside the mask
    """
    
    def __init__(self, politicians: list[tuple[int, str]]):
        """
        Initialize with politician list.
        
        Args:
            politicians: List of (pg_id, full_name) tuples from Neo4j
        """
        # Sort by name length (longest first) to prevent partial overlaps
        self.politicians = sorted(politicians, key=lambda x: len(x[1]), reverse=True)
        logger.info(f"EntityMasker initialized with {len(self.politicians)} politicians")
        
        # Pre-compile a SINGLE giant regex for performance
        # Longest-first order in alternation is critical for correct matching
        names_escaped = [re.escape(p[1]) for p in self.politicians]
        pattern_str = r'\b(' + '|'.join(names_escaped) + r')\b'
        self._pattern = re.compile(pattern_str, re.IGNORECASE)
        
        # Map for fast ID lookup (case-insensitive key)
        self._name_to_id = {name.lower(): pg_id for pg_id, name in self.politicians}
    
    def mask(self, text: str) -> tuple[str, dict[str, str]]:
        """
        Mask all politician names in the text using a single pass regex.
        """
        if not text:
            return text, {}
        
        mappings: dict[str, str] = {}
        
        def _replace_callback(match: re.Match) -> str:
            original_text = match.group(0)
            lookup_name = original_text.lower()
            pg_id = self._name_to_id.get(lookup_name)
            
            if pg_id is not None:
                mask_id = f"[POLITICIAN_ID_{pg_id}]"
                mappings[mask_id] = original_text # Store exact original for unmasking
                return mask_id
            return original_text
            
        # Single pass substitution
        masked_text = self._pattern.sub(_replace_callback, text)
        
        return masked_text, mappings
    
    def unmask(self, masked_text: str, mappings: dict[str, str]) -> str:
        """
        Restore original names from masked text (for debugging/display).
        
        Args:
            masked_text: Text with [POLITICIAN_ID_X] tokens
            mappings: Dict from mask() output
            
        Returns:
            Original text with names restored
        """
        result = masked_text
        for mask_id, name in mappings.items():
            result = result.replace(mask_id, name)
        return result


# Module-level singleton for reuse
_masker_instance: Optional[EntityMasker] = None


async def get_masker() -> EntityMasker:
    """
    Get or create the global EntityMasker instance.
    Loads politicians from Neo4j on first call.
    """
    global _masker_instance
    
    if _masker_instance is None:
        from database import neo4j_client
        politicians = await neo4j_client.load_politicians_for_masking()
        _masker_instance = EntityMasker(politicians)
    
    return _masker_instance


def reset_masker():
    """Reset the singleton (useful for testing or reloading data)."""
    global _masker_instance
    _masker_instance = None
