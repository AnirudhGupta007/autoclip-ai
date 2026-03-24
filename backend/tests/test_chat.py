"""Tests for chat intent parsing and response generation."""
import pytest
from autoclip.pipeline.state import ClipConfig, Moment, ProducedClip
from autoclip.pipeline.chat import intent_to_clip_configs, generate_chat_response


class TestIntentToClipConfigs:
    def test_default_params(self):
        params = {"count": 4, "length": 30, "style": "any", "frame": "9:16"}
        configs = intent_to_clip_configs(params)
        assert len(configs) == 4
        assert all(c.length == 30 for c in configs)
        assert all(c.style == "any" for c in configs)
        assert all(c.frame == "9:16" for c in configs)

    def test_custom_params(self):
        params = {"count": 2, "length": 60, "style": "funny", "frame": "1:1"}
        configs = intent_to_clip_configs(params)
        assert len(configs) == 2
        assert all(c.length == 60 for c in configs)
        assert all(c.style == "funny" for c in configs)
        assert all(c.frame == "1:1" for c in configs)

    def test_clamps_count(self):
        configs = intent_to_clip_configs({"count": 50})
        assert len(configs) == 10  # max 10

        configs = intent_to_clip_configs({"count": 0})
        assert len(configs) == 1  # min 1

    def test_clamps_length(self):
        configs = intent_to_clip_configs({"count": 1, "length": 5})
        assert configs[0].length == 15  # min 15

        configs = intent_to_clip_configs({"count": 1, "length": 300})
        assert configs[0].length == 90  # max 90

    def test_invalid_style_defaults_to_any(self):
        configs = intent_to_clip_configs({"count": 1, "style": "invalid_style"})
        assert configs[0].style == "any"

    def test_invalid_frame_defaults(self):
        configs = intent_to_clip_configs({"count": 1, "frame": "4:3"})
        assert configs[0].frame == "9:16"


class TestGenerateChatResponse:
    def test_greeting_response(self):
        response = generate_chat_response("greeting", {})
        assert "upload" in response.lower() or "video" in response.lower()

    def test_generate_clips_response(self):
        clips = [
            ProducedClip(
                id="abc", title="Test Clip", start_time=0, end_time=30,
                duration=30, file_path="/test.mp4", thumbnail_path=None,
                transcript="test", scores={"overall": 8.5}, overall_score=8.5,
                frame="9:16", style_tags=["funny"],
            ),
        ]
        response = generate_chat_response("generate_clips", {}, clips=clips)
        assert "Test Clip" in response
        assert "8.5" in response
        assert "1" in response  # count

    def test_generate_clips_empty(self):
        response = generate_chat_response("generate_clips", {}, clips=[])
        # Should still return a message, not crash
        assert isinstance(response, str)

    def test_ask_question_with_moments(self):
        moments = [
            Moment(
                start=10, end=25, visual_energy=0.8, audio_energy=0.7,
                text_hook_strength=0.9, convergence_score=0.85,
                style_tags=["funny"], description="Speaker tells joke",
                transcript="test",
            ),
        ]
        response = generate_chat_response("ask_question", {}, moment_map=moments)
        assert "1" in response  # 1 moment

    def test_error_response(self):
        response = generate_chat_response("generate_clips", {}, error="API timeout")
        assert "API timeout" in response

    def test_modify_clip_response(self):
        clips = [
            ProducedClip(
                id="abc", title="Updated Clip", start_time=0, end_time=45,
                duration=45, file_path="/test.mp4", thumbnail_path=None,
                transcript="test", scores={}, overall_score=7.0,
                frame="9:16", style_tags=[],
            ),
        ]
        response = generate_chat_response("modify_clip", {"clip_index": 1}, clips=clips)
        assert "Updated Clip" in response or "clip" in response.lower()

    def test_export_response(self):
        response = generate_chat_response("export", {})
        assert "download" in response.lower()
