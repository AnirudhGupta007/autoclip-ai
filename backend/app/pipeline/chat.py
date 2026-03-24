"""Chat-driven interface — parses user messages into pipeline actions."""
import json
import time
from dataclasses import asdict
from google import genai
from app.config import GEMINI_API_KEY, GEMINI_RPM_DELAY
from app.pipeline.state import ClipConfig


def parse_user_intent(message: str, has_video: bool, has_analysis: bool, has_clips: bool) -> dict:
    """
    Parse a user chat message into a structured intent using Gemini.

    Returns:
        {
            "intent": "generate_clips" | "modify_clip" | "ask_question" | "export" | "greeting",
            "params": { ... }  # intent-specific parameters
        }
    """
    client = genai.Client(api_key=GEMINI_API_KEY)

    context = f"""Current state:
- Video uploaded: {has_video}
- Video analyzed: {has_analysis}
- Clips generated: {has_clips}"""

    prompt = f"""You are a chat intent parser for a video clipping AI tool.
Parse the user's message into a structured intent.

{context}

User message: "{message}"

Possible intents:
1. "generate_clips" — user wants clips from their video
   params: count (int, 1-10), length (int seconds: 15/30/60/90), style (funny/dramatic/educational/motivational/controversial/any), frame (9:16/1:1/16:9)
   Examples: "give me 4 tiktok clips", "make 3 funny clips under 30 seconds", "I need youtube shorts"

2. "modify_clip" — user wants to change a specific clip
   params: clip_index (int, 1-based), action (shorten/lengthen/different_moment/change_frame), new_frame (9:16/1:1/16:9), new_length (int)
   Examples: "make clip 2 longer", "change clip 3 to square format", "give me a different clip 1"

3. "export" — user wants to download clips
   params: clip_index (int or "all"), format (9:16/1:1/16:9 or null)
   Examples: "download all clips", "give me clip 2 in youtube format", "export as zip"

4. "ask_question" — user is asking about the video or clips
   params: question (string)
   Examples: "what moments did you find?", "why did you pick clip 3?", "show me the moment map"

5. "greeting" — hello, thanks, etc.
   params: {{}}

Infer defaults when not specified:
- If user says "tiktok" or "reels" → frame = "9:16"
- If user says "youtube" or "shorts" → could be "9:16" for shorts or "16:9" for regular
- If user says "instagram" or "square" → frame = "1:1"
- If no count specified → default 4
- If no length specified → default 30
- If no style specified → default "any"
- If no frame specified → default "9:16"

Return ONLY valid JSON:
{{"intent": "...", "params": {{...}}}}

JSON:"""

    time.sleep(GEMINI_RPM_DELAY)
    response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
    text = response.text.strip()

    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        result = json.loads(text.strip())
    except json.JSONDecodeError:
        result = {"intent": "ask_question", "params": {"question": message}}

    return result


def intent_to_clip_configs(params: dict) -> list[ClipConfig]:
    """Convert parsed intent params to ClipConfig list."""
    count = params.get("count", 4)
    length = params.get("length", 30)
    style = params.get("style", "any")
    frame = params.get("frame", "9:16")

    # Clamp values
    count = max(1, min(10, count))
    length = max(15, min(90, length))

    valid_styles = {"funny", "dramatic", "educational", "motivational", "controversial", "any"}
    if style not in valid_styles:
        style = "any"

    valid_frames = {"9:16", "1:1", "16:9"}
    if frame not in valid_frames:
        frame = "9:16"

    return [
        ClipConfig(length=length, style=style, frame=frame)
        for _ in range(count)
    ]


def generate_chat_response(
    intent: str,
    params: dict,
    clips: list = None,
    moment_map: list = None,
    error: str = None,
) -> str:
    """Generate a natural language response based on intent and results."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    if error:
        return f"Something went wrong: {error}. Try again or upload a different video."

    if intent == "greeting":
        return "Hey! Upload a video and tell me what kind of clips you want. For example: 'Give me 4 funny TikTok clips under 30 seconds'."

    if intent == "generate_clips" and clips:
        clip_summaries = []
        for i, clip in enumerate(clips, 1):
            scores = clip.scores if hasattr(clip, "scores") else clip.get("scores", {})
            overall = clip.overall_score if hasattr(clip, "overall_score") else clip.get("overall_score", 0)
            title = clip.title if hasattr(clip, "title") else clip.get("title", "Untitled")
            duration = clip.duration if hasattr(clip, "duration") else clip.get("duration", 0)
            frame = clip.frame if hasattr(clip, "frame") else clip.get("frame", "9:16")

            clip_summaries.append(
                f"[{i}] \"{title}\" — {duration:.0f}s — {frame} — score {overall:.1f}/10"
            )

        clips_text = "\n".join(clip_summaries)
        count = len(clips)
        return f"Found {count} clips for you:\n\n{clips_text}\n\nYou can say things like 'make clip 2 longer', 'change clip 1 to square format', or 'download all'."

    if intent == "modify_clip" and clips:
        idx = params.get("clip_index", 1) - 1
        if 0 <= idx < len(clips):
            clip = clips[idx]
            title = clip.title if hasattr(clip, "title") else clip.get("title", "Untitled")
            return f"Updated clip {idx + 1}: \"{title}\". Preview it above."
        return "I couldn't find that clip. Check the clip number and try again."

    if intent == "ask_question" and moment_map:
        count = len(moment_map)
        top_3 = moment_map[:3]
        moments_text = "\n".join(
            f"- {m.description} ({m.start:.0f}s-{m.end:.0f}s, convergence: {m.convergence_score:.2f})"
            for m in top_3
        )
        return f"I found {count} interesting moments in your video. Top 3:\n\n{moments_text}\n\nTell me what kind of clips you want from these!"

    if intent == "export":
        return "Your clips are ready for download! Click the download buttons above each clip."

    return "I'm not sure what you meant. Try something like 'give me 4 funny clips under 30 seconds' or 'make clip 2 shorter'."
