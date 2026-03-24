"""Tests for pipeline state definitions."""
import pytest
from autoclip.pipeline.state import (
    VisualSignal, AudioSignal, TextSegment, Moment, ClipConfig, ProducedClip, PipelineState
)


class TestVisualSignal:
    def test_create_visual_signal(self):
        signal = VisualSignal(
            timestamp=5.0,
            energy=0.8,
            emotion="happy",
            emotion_confidence=0.9,
            description="Speaker smiling and gesturing",
        )
        assert signal.timestamp == 5.0
        assert signal.energy == 0.8
        assert signal.emotion == "happy"
        assert signal.has_text_on_screen is False
        assert signal.scene_type == "talking_head"

    def test_visual_signal_with_all_fields(self):
        signal = VisualSignal(
            timestamp=10.0,
            energy=0.6,
            emotion="surprised",
            emotion_confidence=0.75,
            description="Slide with chart visible",
            has_text_on_screen=True,
            scene_type="presentation",
        )
        assert signal.has_text_on_screen is True
        assert signal.scene_type == "presentation"


class TestAudioSignal:
    def test_create_audio_signal(self):
        signal = AudioSignal(
            timestamp=3.0,
            energy=0.7,
            speech_pace=180.0,
            event_type="speech",
            pitch_change=0.3,
        )
        assert signal.timestamp == 3.0
        assert signal.event_type == "speech"
        assert signal.speech_pace == 180.0

    def test_audio_signal_laughter(self):
        signal = AudioSignal(
            timestamp=15.0,
            energy=0.9,
            speech_pace=0.0,
            event_type="laughter",
            pitch_change=0.8,
        )
        assert signal.event_type == "laughter"
        assert signal.energy == 0.9


class TestTextSegment:
    def test_create_text_segment(self):
        seg = TextSegment(
            start=10.0,
            end=25.0,
            text="This is a really important moment",
            hook_type="hot_take",
            hook_strength=0.85,
            topic="startup advice",
            is_complete=True,
        )
        assert seg.start == 10.0
        assert seg.hook_type == "hot_take"
        assert seg.is_complete is True


class TestMoment:
    def test_create_moment(self):
        moment = Moment(
            start=30.0,
            end=60.0,
            visual_energy=0.8,
            audio_energy=0.7,
            text_hook_strength=0.9,
            convergence_score=0.85,
            style_tags=["funny", "story"],
            description="Speaker tells a joke",
            transcript="And then I realized the database was just a spreadsheet",
        )
        assert moment.convergence_score == 0.85
        assert "funny" in moment.style_tags
        assert moment.end - moment.start == 30.0


class TestClipConfig:
    def test_default_config(self):
        config = ClipConfig()
        assert config.moment is None
        assert config.length == 30
        assert config.style == "any"
        assert config.frame == "9:16"
        assert config.caption_style == "bold_pop"

    def test_custom_config(self):
        config = ClipConfig(
            moment=45.0,
            length=60,
            style="funny",
            frame="1:1",
            caption_style="karaoke_sweep",
        )
        assert config.moment == 45.0
        assert config.length == 60
        assert config.frame == "1:1"


class TestProducedClip:
    def test_create_produced_clip(self):
        clip = ProducedClip(
            id="abc123",
            title="The Big Reveal",
            start_time=30.0,
            end_time=60.0,
            duration=30.0,
            file_path="/outputs/test/final.mp4",
            thumbnail_path="/outputs/test/thumb.jpg",
            transcript="And that changed everything",
            scores={"hook": 8, "emotion": 7, "overall": 7.5},
            overall_score=7.5,
            frame="9:16",
            style_tags=["dramatic"],
        )
        assert clip.id == "abc123"
        assert clip.duration == 30.0
        assert clip.scores["hook"] == 8
