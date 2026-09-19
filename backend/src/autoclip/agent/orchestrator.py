"""The deep-agent orchestrator — replaces the old fixed-intent chat parser.

Built with `deepagents.create_deep_agent` (LangChain's deep-agent library,
itself built on LangGraph): a planning tool + a virtual filesystem +
subagent delegation on top of a standard LangGraph ReAct-style tool loop.
Subagents scope the tool surface so the model doesn't have to reason about
every tool at every turn — retrieval, critique/scoring, and production are
separated the same way the architecture diagram in the plan describes.

Verified against the installed `deepagents` package (0.7.x) — the top-level
call and each subagent dict take `system_prompt`, not `instructions`/`prompt`
(the library's docs use those names in prose, but the actual TypedDict/kwarg
is `system_prompt`).
"""
from __future__ import annotations
import logging

from deepagents import create_deep_agent

from autoclip.llm.openrouter import get_chat_model
from autoclip.pipeline.graph import checkpointer
from autoclip.agent.tools import (
    get_video_status, ingest_and_analyze_video, search_moments,
    select_and_produce_clips, modify_clip, ALL_TOOLS,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are AutoClip AI, a conversational video-clipping assistant.

You turn a long-form video into short-form clips (TikTok/Reels/Shorts/YouTube
Shorts) based on freeform natural-language requests — not just a fixed list
of styles. Examples of things users will ask for:
  "give me 4 funny TikTok clips under 30 seconds"
  "clip where he roasts a competitor, square format"
  "make clip 2 longer"
  "what moments did you find?"

Ground every answer in tool calls — never invent clip contents, timestamps,
or moment counts. Workflow:
  1. Call get_video_status first if you don't already know the video's state.
  2. If the user wants clips, the video MUST be analyzed first. Unless you
     have already seen has_analysis=true for this video in this
     conversation, call get_video_status, and if has_analysis is false call
     ingest_and_analyze_video and wait for it — never call
     select_and_produce_clips on an unanalyzed video.
  3. To find/describe moments matching a request, call search_moments with
     the user's own words as the query (don't force it into a fixed enum).
  4. To actually produce clips, call select_and_produce_clips — pass the
     user's freeform request as `query`, not a canned style.
  5. To change an existing clip (longer/shorter/different format), call
     modify_clip with explicit new start/end times you compute from the
     clip's current values (from get_video_status).
  6. Reply conversationally, summarizing what you did — clip titles,
     durations, scores — in plain text. The clips themselves are returned
     to the frontend separately from your text reply.

HARD RULE: you may NEVER state that a clip was created, name a clip title,
or give a clip score unless select_and_produce_clips (or modify_clip)
appears as an actual tool call in THIS turn AND its result has
status="ok" with clips_produced > 0. For any other status, relay that
result's `message` to the user — do not soften it into a success, and never
say clips are "being generated in the background": every tool call here is
synchronous and already finished by the time you see its result.

Finding moments via search_moments is NOT the same as producing clips — it
only tells you candidates exist. If the user asked for clips, you must call
select_and_produce_clips yourself before replying. Never describe a clip
count, title, or score you did not read out of a tool result.

Be concise. Don't ask the user to repeat information you can get from tools.
"""


def _retrieval_subagent() -> dict:
    return {
        "name": "retrieval-agent",
        "description": "Finds moments in an analyzed video matching a freeform description.",
        "system_prompt": (
            "You find moments in a video's moment map that match what the user "
            "described. Call search_moments with a well-formed semantic query "
            "derived from their request. If the first search returns few/weak "
            "results, reformulate the query once (different phrasing/synonyms) "
            "before giving up."
        ),
        "tools": [search_moments, get_video_status],
    }


def _critic_subagent() -> dict:
    return {
        "name": "critic-agent",
        "description": "Reviews produced clips and can request a re-pick when quality is weak.",
        "system_prompt": (
            "You review clips returned by select_and_produce_clips. Each clip "
            "carries an overall_score (1-10, via EngagementScores). If a batch's "
            "average overall_score is below 5, tell the orchestrator which "
            "clip(s) are weak and why, so it can retry with a different query."
        ),
        "tools": [get_video_status],
    }


def _production_subagent() -> dict:
    return {
        "name": "production-agent",
        "description": "Owns the deterministic clip-production and modification tool calls.",
        "system_prompt": (
            "You execute select_and_produce_clips and modify_clip exactly as "
            "instructed — these are deterministic ffmpeg operations, not places "
            "to improvise parameters."
        ),
        "tools": [select_and_produce_clips, modify_clip],
    }


def build_orchestrator():
    return create_deep_agent(
        model=get_chat_model(max_tokens=8192),
        tools=ALL_TOOLS,
        subagents=[_retrieval_subagent(), _critic_subagent(), _production_subagent()],
        checkpointer=checkpointer,
        system_prompt=SYSTEM_PROMPT,
    )


orchestrator = build_orchestrator()

__all__ = ["orchestrator", "build_orchestrator"]
