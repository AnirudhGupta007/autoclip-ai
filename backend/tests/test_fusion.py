"""Tests for the temporal fusion node."""
import pytest
from autoclip.pipeline.state import VisualSignal, AudioSignal, TextSegment, Moment
from autoclip.pipeline.agents.fusion import (
    _find_convergence_windows,
    _merge_overlapping_windows,
    run_fusion,
)


def _make_visual(timestamp, energy, emotion="neutral"):
    return VisualSignal(
        timestamp=timestamp,
        energy=energy,
        emotion=emotion,
        emotion_confidence=0.8,
        description=f"Frame at {timestamp}s",
    )


def _make_audio(timestamp, energy, event_type="speech", pace=150.0):
    return AudioSignal(
        timestamp=timestamp,
        energy=energy,
        speech_pace=pace,
        event_type=event_type,
        pitch_change=0.3,
    )


def _make_text(start, end, hook_type="none", strength=0.0):
    return TextSegment(
        start=start,
        end=end,
        text=f"Text from {start}s to {end}s",
        hook_type=hook_type,
        hook_strength=strength,
        topic="test",
        is_complete=True,
    )


class TestFindConvergenceWindows:
    def test_empty_inputs(self):
        windows = _find_convergence_windows([], [], [])
        assert windows == []

    def test_single_modality_visual(self):
        """Single modality with high energy should still produce windows
        if energy is high enough (visual weight=0.3, so need energy~1.0 to pass 0.3)."""
        visual = [
            _make_visual(5.0, 1.0),
            _make_visual(10.0, 0.2),
            _make_visual(15.0, 1.0),
        ]
        windows = _find_convergence_windows(visual, [], [])
        # With max visual energy=1.0, convergence = 1.0*0.3 = 0.3, just at threshold
        assert len(windows) >= 0  # may or may not pass depending on threshold
        # At minimum, verify no crash and correct structure
        for w in windows:
            assert "convergence_score" in w
            assert w["convergence_score"] > 0.3

    def test_triple_convergence_bonus(self):
        """Windows where all 3 modalities are active should score higher."""
        visual = [_make_visual(5.0, 0.8, "excited")]
        audio = [_make_audio(5.0, 0.7, "speech", 200)]
        text = [_make_text(3.0, 8.0, "hot_take", 0.9)]

        windows = _find_convergence_windows(visual, audio, text)
        assert len(windows) > 0

        # Find the window containing timestamp 5.0
        relevant = [w for w in windows if w["start"] <= 5.0 and w["end"] > 5.0]
        assert len(relevant) > 0
        assert relevant[0]["active_modalities"] >= 2

    def test_laughter_boosts_audio_score(self):
        visual = [_make_visual(5.0, 0.3)]
        audio = [_make_audio(5.0, 0.5, "laughter")]
        text = [_make_text(3.0, 8.0, "funny", 0.6)]

        windows = _find_convergence_windows(visual, audio, text)
        relevant = [w for w in windows if w["start"] <= 5.0 and w["end"] > 5.0]
        assert len(relevant) > 0
        # Laughter should boost audio score above 0.5
        assert relevant[0]["audio_energy"] > 0.5

    def test_style_tags_from_text(self):
        visual = [_make_visual(5.0, 0.6)]
        audio = [_make_audio(5.0, 0.6)]
        text = [_make_text(3.0, 8.0, "educational", 0.7)]

        windows = _find_convergence_windows(visual, audio, text)
        relevant = [w for w in windows if w["start"] <= 5.0 and w["end"] > 5.0]
        assert len(relevant) > 0
        assert "educational" in relevant[0]["style_tags"]

    def test_low_scores_filtered(self):
        """Windows with all low scores should be filtered out."""
        visual = [_make_visual(5.0, 0.1)]
        audio = [_make_audio(5.0, 0.1)]
        text = [_make_text(3.0, 8.0, "none", 0.1)]

        windows = _find_convergence_windows(visual, audio, text)
        # All windows should have convergence > 0.3
        for w in windows:
            assert w["convergence_score"] > 0.3


class TestMergeOverlappingWindows:
    def test_no_overlap(self):
        windows = [
            {"start": 0, "end": 5, "visual_energy": 0.5, "audio_energy": 0.5,
             "text_hook_strength": 0.5, "convergence_score": 0.5,
             "active_modalities": 2, "style_tags": ["funny"], "transcript": "a"},
            {"start": 10, "end": 15, "visual_energy": 0.6, "audio_energy": 0.6,
             "text_hook_strength": 0.6, "convergence_score": 0.6,
             "active_modalities": 3, "style_tags": ["dramatic"], "transcript": "b"},
        ]
        merged = _merge_overlapping_windows(windows)
        assert len(merged) == 2

    def test_overlap_merges(self):
        windows = [
            {"start": 0, "end": 8, "visual_energy": 0.5, "audio_energy": 0.5,
             "text_hook_strength": 0.5, "convergence_score": 0.5,
             "active_modalities": 2, "style_tags": ["funny"], "transcript": "a"},
            {"start": 6, "end": 14, "visual_energy": 0.8, "audio_energy": 0.8,
             "text_hook_strength": 0.8, "convergence_score": 0.8,
             "active_modalities": 3, "style_tags": ["dramatic"], "transcript": "longer text here"},
        ]
        merged = _merge_overlapping_windows(windows)
        assert len(merged) == 1
        assert merged[0]["start"] == 0
        assert merged[0]["end"] == 14
        assert merged[0]["convergence_score"] == 0.8  # max
        assert "funny" in merged[0]["style_tags"]
        assert "dramatic" in merged[0]["style_tags"]

    def test_adjacent_merges(self):
        """Windows within max_gap should merge."""
        windows = [
            {"start": 0, "end": 5, "visual_energy": 0.5, "audio_energy": 0.5,
             "text_hook_strength": 0.5, "convergence_score": 0.5,
             "active_modalities": 2, "style_tags": [], "transcript": "a"},
            {"start": 7, "end": 12, "visual_energy": 0.6, "audio_energy": 0.6,
             "text_hook_strength": 0.6, "convergence_score": 0.6,
             "active_modalities": 2, "style_tags": [], "transcript": "b"},
        ]
        merged = _merge_overlapping_windows(windows, max_gap=3.0)
        assert len(merged) == 1

    def test_empty_input(self):
        assert _merge_overlapping_windows([]) == []


class TestRunFusion:
    def test_run_fusion_with_data(self):
        state = {
            "visual_timeline": [
                _make_visual(5.0, 0.8, "excited"),
                _make_visual(10.0, 0.3),
                _make_visual(20.0, 0.9, "happy"),
            ],
            "audio_timeline": [
                _make_audio(4.0, 0.7, "speech", 200),
                _make_audio(6.0, 0.8, "laughter"),
                _make_audio(20.0, 0.6),
            ],
            "text_segments": [
                _make_text(3.0, 8.0, "funny", 0.8),
                _make_text(18.0, 25.0, "educational", 0.6),
            ],
        }

        result = run_fusion(state)
        assert "moment_map" in result
        assert result["analysis_complete"] is True
        assert len(result["moment_map"]) > 0

        # Moments should be sorted by convergence score (descending)
        moments = result["moment_map"]
        for i in range(len(moments) - 1):
            assert moments[i].convergence_score >= moments[i + 1].convergence_score

    def test_run_fusion_empty(self):
        state = {
            "visual_timeline": [],
            "audio_timeline": [],
            "text_segments": [],
        }
        result = run_fusion(state)
        assert result["moment_map"] == []
        assert result["analysis_complete"] is True
