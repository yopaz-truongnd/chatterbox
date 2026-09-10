"""Pronunciation Knowledge Service (Phase 5).

Manages proper noun and mythological term pronunciation dictionary,
alias lookup, verification states, and knowledge gap detection.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any
import yaml

from services.narration_planner import scan_pronunciation_candidates
from services.resource_models import (
    PronunciationEntry,
    PronunciationHint,
    PronunciationKnowledge,
    PronunciationStatus,
    RequirementPriority,
    ResourceCategory,
    ResourceGap,
)


def load_pronunciation_knowledge(path: str | Path | None = None) -> PronunciationKnowledge:
    """Load PronunciationKnowledge from knowledge/pronunciation.yaml or provided path."""
    if not path:
        path = Path(__file__).resolve().parent.parent / "knowledge" / "pronunciation.yaml"
    else:
        path = Path(path)

    if not path.exists():
        return PronunciationKnowledge(version=1, terms={})

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            return PronunciationKnowledge.from_dict(data)
    except Exception as e:
        raise ValueError(f"Malformed pronunciation knowledge YAML at {path}: {e}") from e


def normalize_term(term: str) -> str:
    """Normalize a word or phrase for dictionary lookup (lowercase, stripped, no punctuation)."""
    if not term:
        return ""
    # Remove leading/trailing punctuation and whitespace, lowercase
    cleaned = re.sub(r"^[^\w]+|[^\w]+$", "", term.strip().lower())
    # Collapse multiple spaces or hyphens/underscores
    cleaned = re.sub(r"[\s\-_]+", " ", cleaned)
    return cleaned


def lookup_term(term: str, knowledge: PronunciationKnowledge) -> tuple[str | None, PronunciationEntry | None]:
    """Look up a term by canonical name or alias.
    
    Returns:
        (canonical_key, PronunciationEntry) or (None, None) if not found.
    """
    norm_target = normalize_term(term)
    if not norm_target:
        return None, None

    # 1. Direct canonical key match
    for key, entry in knowledge.terms.items():
        if normalize_term(key) == norm_target or normalize_term(entry.display) == norm_target:
            return key, entry

    # 2. Alias match
    for key, entry in knowledge.terms.items():
        for alias in entry.aliases:
            if normalize_term(alias) == norm_target:
                return key, entry

    return None, None


def check_term_status(term: str, knowledge: PronunciationKnowledge) -> tuple[PronunciationStatus, PronunciationEntry | None]:
    """Check the verification status of a term."""
    key, entry = lookup_term(term, knowledge)
    if not entry:
        return PronunciationStatus.UNVERIFIED, None
    return entry.status, entry


def evaluate_script_pronunciation(
    script_text: str,
    knowledge: PronunciationKnowledge,
    explicit_pronunciations: dict[str, str] | None = None,
    required_terms: list[str] | None = None,
) -> dict[str, Any]:
    """Scan script for proper nouns and check against the pronunciation knowledge base.

    Does NOT modify the script text. Produces verified pronunciation overrides and knowledge gaps.
    """
    candidates = scan_pronunciation_candidates(script_text)
    
    # Also include any explicitly required terms
    checked_words: set[str] = set()
    terms_to_check: list[tuple[str, str]] = [] # (word, category)

    for cand in candidates:
        word = cand.get("word", "").strip()
        cat = cand.get("category", "proper_noun")
        if word and word not in checked_words:
            checked_words.add(word)
            terms_to_check.append((word, cat))

    if required_terms:
        for req in required_terms:
            req_clean = req.strip()
            if req_clean and req_clean not in checked_words:
                checked_words.add(req_clean)
                terms_to_check.append((req_clean, "proper_noun"))

    if explicit_pronunciations:
        for exp_k in explicit_pronunciations.keys():
            exp_clean = exp_k.strip()
            if exp_clean and exp_clean not in checked_words:
                checked_words.add(exp_clean)
                terms_to_check.append((exp_clean, "proper_noun"))

    verified_overrides: dict[str, str] = {}
    verified_terms: list[str] = []
    unverified_terms: list[str] = []
    knowledge_gaps: list[ResourceGap] = []

    gap_counter = 1

    for word, category in terms_to_check:
        # If user explicitly supplied pronunciation override, treat as user-supplied verified override
        if explicit_pronunciations and word in explicit_pronunciations:
            override_val = explicit_pronunciations[word]
            verified_overrides[word] = override_val
            verified_terms.append(word)
            continue

        status, entry = check_term_status(word, knowledge)

        if status == PronunciationStatus.VERIFIED and entry:
            verified_terms.append(word)
            hint = entry.pronunciation.tts_hint
            if hint:
                verified_overrides[entry.display] = hint
                if word != entry.display:
                    verified_overrides[word] = hint
        else:
            # Proper noun or required term with missing / unverified / rejected pronunciation
            if category in ("proper_noun", "acronym") or (required_terms and word in required_terms):
                unverified_terms.append(word)
                
                reason_str = "mythological_proper_noun" if category == "proper_noun" else "acronym_or_special_word"
                risk_str = "incorrect_tts_pronunciation"
                
                # If term is explicitly in knowledge but status is unverified or rejected
                if entry and entry.status == PronunciationStatus.REJECTED:
                    reason_str = "rejected_pronunciation"
                    risk_str = "pronunciation_explicitly_rejected"

                gap = ResourceGap(
                    id=f"KG{gap_counter:03d}",
                    type=ResourceCategory.KNOWLEDGE,
                    term=word,
                    priority=RequirementPriority.REQUIRED,
                    used_at=[],
                    wanted={
                        "need": "verified_pronunciation",
                        "display": entry.display if entry else word,
                        "language": entry.language if entry else "zh",
                    },
                    suggested_search=[
                        f"{word} pronunciation guide",
                        f"how to pronounce {word}",
                    ],
                    reason=reason_str,
                    risk=risk_str,
                )
                knowledge_gaps.append(gap)
                gap_counter += 1

    return {
        "verified_overrides": verified_overrides,
        "verified_terms": verified_terms,
        "unverified_terms": unverified_terms,
        "knowledge_gaps": knowledge_gaps,
    }
