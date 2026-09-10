"""Tests for Asset Matching Service — scoring, ranked results, substitute flagging (Phase 18)."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.asset_library_models import AssetCategory, LibraryAsset
from services.asset_library_store import AssetLibraryStore
from services.asset_matching_service import (
    AssetMatchingService,
    _duration_fit_score,
    _energy_fit_score,
    _intent_overlap_score,
    _keyword_match_score,
    _mood_match_score,
)


# ---------------------------------------------------------------------------
# Scoring unit tests
# ---------------------------------------------------------------------------


class TestIntentOverlapScore:
    def test_perfect_overlap(self):
        score = _intent_overlap_score(["forest", "calm"], ["forest", "calm"])
        assert score == 1.0

    def test_no_overlap(self):
        score = _intent_overlap_score(["thunder"], ["forest"])
        assert score == 0.0

    def test_partial_overlap(self):
        score = _intent_overlap_score(["forest", "rain"], ["forest", "thunder"])
        # intersection=1, union=3 → 1/3
        assert abs(score - 1 / 3) < 1e-6

    def test_empty_request_returns_zero(self):
        assert _intent_overlap_score(["forest"], []) == 0.0

    def test_case_insensitive(self):
        score = _intent_overlap_score(["FOREST"], ["forest"])
        assert score == 1.0


class TestKeywordMatchScore:
    def test_all_match(self):
        score = _keyword_match_score(["forest", "calm"], ["forest", "calm"])
        assert score == 1.0

    def test_no_match(self):
        score = _keyword_match_score(["city"], ["forest"])
        assert score == 0.0

    def test_empty_keywords(self):
        assert _keyword_match_score([], ["forest"]) == 0.0

    def test_partial_match(self):
        score = _keyword_match_score(["forest", "river"], ["forest", "thunder"])
        # 1 out of 2 request intents matched
        assert abs(score - 0.5) < 1e-6


class TestMoodMatchScore:
    def test_match(self):
        assert _mood_match_score("tense", "tense") == 1.0

    def test_no_match(self):
        assert _mood_match_score("peaceful", "tense") == 0.0

    def test_no_request_mood_gives_full_score(self):
        assert _mood_match_score("tense", None) == 1.0

    def test_asset_has_no_mood(self):
        assert _mood_match_score(None, "tense") == 0.0

    def test_case_insensitive(self):
        assert _mood_match_score("TENSE", "tense") == 1.0


class TestDurationFitScore:
    def test_exact_match(self):
        assert _duration_fit_score(5000.0, 5000.0) == 1.0

    def test_within_20_percent(self):
        assert _duration_fit_score(5800.0, 5000.0) == 1.0  # 16% over

    def test_no_request_gives_full_score(self):
        assert _duration_fit_score(5000.0, None) == 1.0

    def test_very_far_off_returns_zero(self):
        assert _duration_fit_score(1.0, 10000.0) == 0.0

    def test_moderate_deviation(self):
        score = _duration_fit_score(3000.0, 10000.0)
        assert 0.0 < score < 1.0


class TestEnergyFitScore:
    def test_no_context_gives_full_score(self):
        assert _energy_fit_score(3.0, None) == 1.0

    def test_no_asset_energy_gives_full_score(self):
        assert _energy_fit_score(None, "battle") == 1.0

    def test_climax_expects_high_energy(self):
        score_high = _energy_fit_score(4.5, "climax")
        score_low = _energy_fit_score(1.0, "climax")
        assert score_high > score_low

    def test_quiet_expects_low_energy(self):
        score_low = _energy_fit_score(1.0, "calm and gentle")
        score_high = _energy_fit_score(5.0, "calm and gentle")
        assert score_low > score_high


# ---------------------------------------------------------------------------
# Matching integration tests
# ---------------------------------------------------------------------------


def _make_store(tmp_path: Path) -> AssetLibraryStore:
    return AssetLibraryStore(index_path=tmp_path / "idx.yaml")


def _add_asset(
    store: AssetLibraryStore,
    asset_id: str,
    intents: list[str],
    keywords: list[str] | None = None,
    mood: str | None = None,
    energy: float | None = None,
    duration_ms: float = 5000.0,
    loopable: bool = False,
    category: AssetCategory = AssetCategory.AMBIENCE,
    enabled: bool = True,
) -> LibraryAsset:
    asset = LibraryAsset(
        asset_id=asset_id,
        category=category,
        file_path=f"sfx/{asset_id}.wav",
        sha256=asset_id * 4 + "a" * (64 - len(asset_id) * 4),
        format="wav",
        duration_ms=duration_ms,
        sample_rate=44100,
        channels=1,
        intents=intents,
        keywords=keywords or [],
        mood=mood,
        energy=energy,
        loopable=loopable,
        enabled=enabled,
    )
    store.save_asset(asset)
    return asset


class TestMatchAssets:
    def test_returns_empty_when_no_candidates(self, tmp_path):
        store = _make_store(tmp_path)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest"], AssetCategory.AMBIENCE)
        assert results == []

    def test_single_perfect_match(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast001", ["forest_atmosphere"], category=AssetCategory.AMBIENCE)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest_atmosphere"], AssetCategory.AMBIENCE)
        assert len(results) == 1
        assert results[0].asset_id == "ast001"
        assert results[0].match_score > 0.0

    def test_ranked_by_score_descending(self, tmp_path):
        store = _make_store(tmp_path)
        # ast_a matches perfectly; ast_b has no intent match
        _add_asset(store, "ast_a", ["forest", "calm"], mood="peaceful")
        _add_asset(store, "ast_b", ["city_noise"])
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest", "calm"], AssetCategory.AMBIENCE, mood="peaceful")
        assert results[0].match_score >= results[-1].match_score

    def test_top_k_limits_results(self, tmp_path):
        store = _make_store(tmp_path)
        for i in range(10):
            _add_asset(store, f"ast_{i:03}", ["forest"])
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest"], AssetCategory.AMBIENCE, top_k=3)
        assert len(results) <= 3

    def test_exact_vs_substitute_flag(self, tmp_path):
        store = _make_store(tmp_path)
        # High-score asset → exact
        _add_asset(store, "ast_exact", ["forest_atmosphere"], keywords=["forest", "nature"], mood="peaceful", energy=2.0)
        # Low-score asset → substitute
        _add_asset(store, "ast_sub", ["city_noise"])
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(
            ["forest_atmosphere"],
            AssetCategory.AMBIENCE,
            mood="peaceful",
            story_context="calm and gentle scene",
        )
        high = next((r for r in results if r.asset_id == "ast_exact"), None)
        low = next((r for r in results if r.asset_id == "ast_sub"), None)

        assert high is not None
        assert high.exact_or_substitute == "exact"
        if low is not None:
            assert low.exact_or_substitute == "substitute"

    def test_loopable_filter_excludes_non_loopable(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast_loop", ["forest"], loopable=True)
        _add_asset(store, "ast_noloop", ["forest"], loopable=False)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest"], AssetCategory.AMBIENCE, loopable=True)
        ids = {r.asset_id for r in results}
        assert "ast_loop" in ids
        assert "ast_noloop" not in ids

    def test_disabled_assets_excluded(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast_on", ["forest"], enabled=True)
        _add_asset(store, "ast_off", ["forest"], enabled=False)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest"], AssetCategory.AMBIENCE)
        ids = {r.asset_id for r in results}
        assert "ast_on" in ids
        assert "ast_off" not in ids

    def test_category_filter_respected(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast_amb", ["rain"], category=AssetCategory.AMBIENCE)
        _add_asset(store, "ast_sfx", ["rain"], category=AssetCategory.SFX)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["rain"], AssetCategory.SFX)
        ids = {r.asset_id for r in results}
        assert "ast_sfx" in ids
        assert "ast_amb" not in ids

    def test_match_reasons_are_non_empty(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast_reason", ["thunder"])
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["thunder"], AssetCategory.AMBIENCE)
        assert results[0].match_reasons  # non-empty list

    def test_substitute_never_silently_passed_as_exact(self, tmp_path):
        """Substitute assets must be explicitly marked; never silently labelled 'exact'."""
        store = _make_store(tmp_path)
        _add_asset(store, "ast_weak", ["completely_unrelated"])
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest_atmosphere"], AssetCategory.AMBIENCE)
        for r in results:
            if r.match_score < 0.70:
                assert r.exact_or_substitute == "substitute", (
                    f"Asset {r.asset_id} has score {r.match_score} but is labelled 'exact'"
                )

    def test_duration_affects_score(self, tmp_path):
        store = _make_store(tmp_path)
        _add_asset(store, "ast_dur_near", ["forest"], duration_ms=5100.0)
        _add_asset(store, "ast_dur_far", ["forest"], duration_ms=50000.0)
        svc = AssetMatchingService(store=store)
        results = svc.match_assets(["forest"], AssetCategory.AMBIENCE, duration_ms=5000.0)
        near = next(r for r in results if r.asset_id == "ast_dur_near")
        far = next(r for r in results if r.asset_id == "ast_dur_far")
        assert near.match_score >= far.match_score
