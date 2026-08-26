"""Asset Matching Service (Phase 18).

Ranks library assets against a semantic request using a weighted scoring
formula. Never silently binds substitutes — flags exact vs substitute.
"""

from __future__ import annotations

from services.asset_library_models import AssetCategory, AssetMatchResult, LibraryAsset
from services.asset_library_store import AssetLibraryStore, get_asset_library_store

# ---------------------------------------------------------------------------
# Scoring weights (must sum to 1.0)
# ---------------------------------------------------------------------------
_W_INTENT = 0.40
_W_KEYWORD = 0.20
_W_MOOD = 0.20
_W_DURATION = 0.10
_W_ENERGY = 0.10

# Threshold below which an asset is considered a "substitute" rather than "exact"
_EXACT_THRESHOLD = 0.70


def _intent_overlap_score(asset_intents: list[str], request_intents: list[str]) -> float:
    """Jaccard-like overlap score between intent lists (case-insensitive)."""
    if not request_intents:
        return 0.0
    a = {i.lower() for i in asset_intents}
    r = {i.lower() for i in request_intents}
    if not r:
        return 0.0
    intersection = len(a & r)
    union = len(a | r)
    return intersection / union if union > 0 else 0.0


def _keyword_match_score(asset_keywords: list[str], request_intents: list[str]) -> float:
    """How many request intents appear in asset keyword list."""
    if not request_intents or not asset_keywords:
        return 0.0
    kw = {k.lower() for k in asset_keywords}
    matched = sum(1 for ri in request_intents if ri.lower() in kw)
    return matched / len(request_intents)


def _mood_match_score(asset_mood: str | None, request_mood: str | None) -> float:
    """Binary match: 1.0 if moods match (case-insensitive), 0.0 otherwise.
    If no mood filter is requested, full score is awarded."""
    if request_mood is None:
        return 1.0
    if asset_mood is None:
        return 0.0
    return 1.0 if asset_mood.lower() == request_mood.lower() else 0.0


def _duration_fit_score(asset_duration_ms: float, request_duration_ms: float | None) -> float:
    """Score how well asset duration fits request duration.
    Returns 1.0 if no duration requested, else decays with relative deviation."""
    if request_duration_ms is None or request_duration_ms <= 0:
        return 1.0
    if asset_duration_ms <= 0:
        return 0.0
    max_d = max(asset_duration_ms, request_duration_ms)
    min_d = min(asset_duration_ms, request_duration_ms)
    ratio = max_d / min_d
    if ratio <= 1.20:
        return 1.0
    if ratio >= 4.0:
        return 0.0
    return max(0.0, 1.0 - (ratio - 1.20) / (4.0 - 1.20))


def _energy_fit_score(asset_energy: float | None, story_context: str | None) -> float:
    """Very simple energy heuristic from story context keywords.
    Returns 1.0 if no energy data available to match against."""
    if asset_energy is None:
        return 1.0
    if story_context is None:
        return 1.0
    ctx = story_context.lower()
    if any(k in ctx for k in ("climax", "battle", "intense", "dramatic", "action")):
        expected = 4.0
    elif any(k in ctx for k in ("quiet", "calm", "gentle", "soft", "peace")):
        expected = 1.5
    elif any(k in ctx for k in ("moderate", "normal", "conversation")):
        expected = 2.5
    else:
        return 1.0  # No clear context — give benefit of the doubt

    diff = abs(asset_energy - expected)
    return max(0.0, 1.0 - diff / 5.0)


def _loopable_ok(asset_loopable: bool, request_loopable: bool | None) -> bool:
    """Return False only when loopable is strictly required but asset is not."""
    if request_loopable is True and not asset_loopable:
        return False
    return True


# ---------------------------------------------------------------------------
# Public service
# ---------------------------------------------------------------------------


class AssetMatchingService:
    """Score and rank library assets against a semantic request."""

    def __init__(self, store: AssetLibraryStore | None = None) -> None:
        self._store = store or get_asset_library_store()

    def match_assets(
        self,
        request_intents: list[str],
        category: AssetCategory,
        mood: str | None = None,
        environment: str | None = None,
        duration_ms: float | None = None,
        loopable: bool | None = None,
        story_context: str | None = None,
        top_k: int = 5,
    ) -> list[AssetMatchResult]:
        """Find and rank assets matching the given semantic request.

        Returns up to ``top_k`` results sorted by descending match_score.
        Each result explicitly labels whether it is an exact match or a substitute.
        """
        # Only enabled assets participate in matching
        candidates: list[LibraryAsset] = [
            a
            for a in self._store.list_assets(category=category)
            if a.enabled
        ]

        scored: list[tuple[float, list[str], LibraryAsset]] = []

        for asset in candidates:
            # Hard filter: loopable constraint
            if not _loopable_ok(asset.loopable, loopable):
                continue

            # Soft filter: environment keyword (partial match)
            if environment is not None and asset.environment is not None:
                if environment.lower() not in asset.environment.lower():
                    continue

            reasons: list[str] = []

            # Score components
            intent_score = _intent_overlap_score(asset.intents, request_intents)
            keyword_score = _keyword_match_score(asset.keywords, request_intents)
            mood_score = _mood_match_score(asset.mood, mood)
            duration_score = _duration_fit_score(asset.duration_ms, duration_ms)
            energy_score = _energy_fit_score(asset.energy, story_context)

            total = (
                intent_score * _W_INTENT
                + keyword_score * _W_KEYWORD
                + mood_score * _W_MOOD
                + duration_score * _W_DURATION
                + energy_score * _W_ENERGY
            )

            # Build human-readable reasons
            if intent_score > 0:
                reasons.append(f"intent_overlap={intent_score:.2f}")
            if keyword_score > 0:
                reasons.append(f"keyword_match={keyword_score:.2f}")
            if mood_score > 0 and mood is not None:
                reasons.append(f"mood_match={asset.mood}")
            if duration_score > 0 and duration_ms is not None:
                reasons.append(f"duration_fit={duration_score:.2f}")
            if energy_score > 0 and story_context is not None:
                reasons.append(f"energy_fit={energy_score:.2f}")
            if not reasons:
                reasons.append("category_match_only")

            scored.append((total, reasons, asset))

        # Sort descending by score
        scored.sort(key=lambda t: t[0], reverse=True)

        results: list[AssetMatchResult] = []
        for score, reasons, asset in scored[:top_k]:
            exact_or_sub = "exact" if score >= _EXACT_THRESHOLD else "substitute"
            results.append(
                AssetMatchResult(
                    asset_id=asset.asset_id,
                    match_score=round(score, 4),
                    match_reasons=reasons,
                    exact_or_substitute=exact_or_sub,
                    license=asset.license,
                    preview_artifact=None,
                )
            )

        return results


# Module-level singleton
_matching_service: AssetMatchingService | None = None


def get_asset_matching_service() -> AssetMatchingService:
    global _matching_service
    if _matching_service is None:
        _matching_service = AssetMatchingService()
    return _matching_service
