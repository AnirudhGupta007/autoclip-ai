"""Tests for LangGraph pipeline graph structure."""
import pytest
from langgraph.types import Send
from autoclip.pipeline.graph import (
    build_pipeline_graph,
    build_analysis_subgraph,
    build_generation_subgraph,
    route_by_video_type,
    route_after_fusion,
    route_analysis_check,
    pipeline,
    generation_only,
)
from autoclip.pipeline.state import Moment


class TestConditionalRouting:
    def test_podcast_sends_two_agents(self):
        """Podcast should dispatch only audio + text (no visual)."""
        state = {"video_type": "podcast"}
        sends = route_by_video_type(state)
        assert all(isinstance(s, Send) for s in sends)
        targets = {s.node for s in sends}
        assert targets == {"audio_agent", "text_agent"}
        assert "visual_agent" not in targets

    def test_talking_head_sends_three_agents(self):
        """Non-podcast should dispatch all three agents in parallel."""
        state = {"video_type": "talking_head"}
        sends = route_by_video_type(state)
        targets = {s.node for s in sends}
        assert targets == {"visual_agent", "audio_agent", "text_agent"}

    def test_presentation_sends_three_agents(self):
        state = {"video_type": "presentation"}
        sends = route_by_video_type(state)
        targets = {s.node for s in sends}
        assert "visual_agent" in targets

    def test_mixed_sends_three_agents(self):
        state = {"video_type": "mixed"}
        sends = route_by_video_type(state)
        assert len(sends) == 3

    def test_default_sends_three_agents(self):
        state = {}
        sends = route_by_video_type(state)
        targets = {s.node for s in sends}
        assert targets == {"visual_agent", "audio_agent", "text_agent"}

    def test_send_passes_state(self):
        """Each Send should carry the full state for the agent."""
        state = {"video_type": "talking_head", "video_path": "/test.mp4"}
        sends = route_by_video_type(state)
        for s in sends:
            assert s.arg == state

    def test_after_fusion_has_moments(self):
        state = {
            "moment_map": [
                Moment(0, 10, 0.5, 0.5, 0.5, 0.5, 2, [], "", ""),
            ]
        }
        assert route_after_fusion(state) == "has_moments"

    def test_after_fusion_no_moments(self):
        state = {"moment_map": []}
        assert route_after_fusion(state) == "no_moments"

    def test_after_fusion_missing_key(self):
        state = {}
        assert route_after_fusion(state) == "no_moments"

    def test_analysis_check_needs_analysis(self):
        state = {"analysis_complete": False}
        assert route_analysis_check(state) == "needs_analysis"

    def test_analysis_check_skip_to_selection(self):
        state = {"analysis_complete": True}
        assert route_analysis_check(state) == "skip_to_selection"

    def test_analysis_check_missing_key(self):
        state = {}
        assert route_analysis_check(state) == "needs_analysis"


class TestSubgraphStructure:
    def test_analysis_subgraph_compiles(self):
        graph = build_analysis_subgraph()
        compiled = graph.compile()
        assert compiled is not None

    def test_analysis_subgraph_has_nodes(self):
        graph = build_analysis_subgraph()
        node_names = set(graph.nodes.keys())
        expected = {"classifier", "visual_agent", "audio_agent", "text_agent", "fusion"}
        assert expected.issubset(node_names)

    def test_generation_subgraph_compiles(self):
        graph = build_generation_subgraph()
        compiled = graph.compile()
        assert compiled is not None

    def test_generation_subgraph_has_nodes(self):
        graph = build_generation_subgraph()
        node_names = set(graph.nodes.keys())
        assert "clip_selector" in node_names
        assert "production" in node_names
        assert "ffmpeg_tools" in node_names
        # Should NOT have analysis nodes
        assert "transcription" not in node_names
        assert "visual_agent" not in node_names


class TestMainPipelineGraph:
    def test_pipeline_graph_compiles(self):
        graph = build_pipeline_graph()
        # Compile without checkpointer for testing
        compiled = graph.compile()
        assert compiled is not None

    def test_pipeline_graph_has_nodes(self):
        graph = build_pipeline_graph()
        node_names = set(graph.nodes.keys())
        assert "transcription" in node_names
        assert "scene_detection" in node_names
        assert "analysis" in node_names  # subgraph node
        assert "generation" in node_names  # subgraph node

    def test_compiled_pipeline_exists(self):
        """The pre-compiled pipeline with checkpointer should be importable."""
        assert pipeline is not None

    def test_compiled_generation_exists(self):
        assert generation_only is not None


class TestToolIntegration:
    def test_production_tools_registered(self):
        """Verify FFmpeg tools are available in generation subgraph."""
        from autoclip.pipeline.tools import PRODUCTION_TOOLS, ANALYSIS_TOOLS
        assert len(PRODUCTION_TOOLS) == 5
        assert len(ANALYSIS_TOOLS) == 4

        # Check tool names
        prod_names = {t.name for t in PRODUCTION_TOOLS}
        assert "tool_cut_clip" in prod_names
        assert "tool_burn_captions" in prod_names
        assert "tool_reframe_video" in prod_names
        assert "tool_generate_thumbnail" in prod_names

        analysis_names = {t.name for t in ANALYSIS_TOOLS}
        assert "tool_extract_frames" in analysis_names
        assert "tool_detect_scenes" in analysis_names
