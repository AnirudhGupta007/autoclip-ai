"""Tests for LangGraph pipeline graph structure."""
import pytest
from app.pipeline.graph import (
    build_analysis_graph,
    build_generation_graph,
    should_skip_visual,
    after_fusion,
)
from app.pipeline.state import Moment


class TestConditionalRouting:
    def test_skip_visual_for_podcast(self):
        state = {"video_type": "podcast"}
        assert should_skip_visual(state) == "skip_visual"

    def test_run_visual_for_talking_head(self):
        state = {"video_type": "talking_head"}
        assert should_skip_visual(state) == "run_visual"

    def test_run_visual_for_presentation(self):
        state = {"video_type": "presentation"}
        assert should_skip_visual(state) == "run_visual"

    def test_run_visual_for_mixed(self):
        state = {"video_type": "mixed"}
        assert should_skip_visual(state) == "run_visual"

    def test_run_visual_default(self):
        state = {}
        assert should_skip_visual(state) == "run_visual"

    def test_after_fusion_has_moments(self):
        state = {
            "moment_map": [
                Moment(0, 10, 0.5, 0.5, 0.5, 0.5, [], "", ""),
            ]
        }
        assert after_fusion(state) == "has_moments"

    def test_after_fusion_no_moments(self):
        state = {"moment_map": []}
        assert after_fusion(state) == "no_moments"

    def test_after_fusion_missing_key(self):
        state = {}
        assert after_fusion(state) == "no_moments"


class TestGraphStructure:
    def test_analysis_graph_compiles(self):
        graph = build_analysis_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_generation_graph_compiles(self):
        graph = build_generation_graph()
        compiled = graph.compile()
        assert compiled is not None

    def test_analysis_graph_has_nodes(self):
        graph = build_analysis_graph()
        # Check that key nodes exist
        node_names = set(graph.nodes.keys())
        expected_nodes = {
            "transcription", "scene_detection", "classifier",
            "visual_agent", "audio_agent", "text_agent",
            "fusion", "clip_selector", "production",
        }
        assert expected_nodes.issubset(node_names)

    def test_generation_graph_has_nodes(self):
        graph = build_generation_graph()
        node_names = set(graph.nodes.keys())
        assert "clip_selector" in node_names
        assert "production" in node_names
        # Should NOT have analysis nodes
        assert "transcription" not in node_names
        assert "visual_agent" not in node_names
