"""Animated caption generation in ASS format with multiple styles."""
from pathlib import Path
from app.utils.subtitle import seconds_to_ass_time, build_ass_file


def _group_words(words: list[dict], max_words: int = 5) -> list[list[dict]]:
    """Group words into subtitle blocks of max_words."""
    groups = []
    for i in range(0, len(words), max_words):
        groups.append(words[i:i + max_words])
    return groups


def _ass_color(hex_color: str) -> str:
    """Convert hex (#RRGGBB) to ASS color (&HBBGGRR&)."""
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H00{b}{g}{r}&"


WHITE = _ass_color("#FFFFFF")
YELLOW = _ass_color("#FFFF00")
GRAY = _ass_color("#808080")
CYAN = _ass_color("#00CEC9")
PURPLE = _ass_color("#6C5CE7")
BLACK = _ass_color("#000000")
TRANSPARENT = "&H80000000&"


# --- Style definitions ---

STYLE_DEFS = {
    "bold_pop": {
        "style_line": f"Style: Default,Arial,72,{WHITE},&H000000FF&,{BLACK},{TRANSPARENT},-1,0,0,0,100,100,0,0,1,4,2,2,30,30,60,1",
        "highlight_color": YELLOW,
    },
    "minimal_clean": {
        "style_line": f"Style: Default,Helvetica Neue,60,{WHITE},&H000000FF&,&H40000000&,&H40000000&,0,0,0,0,100,100,0,0,1,2,1,2,30,30,50,1",
        "highlight_color": CYAN,
    },
    "karaoke_sweep": {
        "style_line": f"Style: Default,Arial Black,68,{GRAY},&H000000FF&,{BLACK},{TRANSPARENT},-1,0,0,0,100,100,0,0,1,3,2,2,30,30,60,1",
        "highlight_color": WHITE,
    },
    "bounce_in": {
        "style_line": f"Style: Default,Impact,74,{WHITE},&H000000FF&,{PURPLE},{TRANSPARENT},-1,0,0,0,100,100,0,0,1,4,2,2,30,30,60,1",
        "highlight_color": YELLOW,
    },
    "glow": {
        "style_line": f"Style: Default,Arial,70,{WHITE},&H000000FF&,{CYAN},{TRANSPARENT},-1,0,0,0,100,100,0,0,1,5,3,2,30,30,60,1",
        "highlight_color": CYAN,
    },
}


def _generate_bold_pop_events(groups: list[list[dict]], clip_start: float) -> str:
    """Bold Pop: White text, current word highlighted yellow with scale-up."""
    lines = []
    for group in groups:
        g_start = seconds_to_ass_time(group[0]["start"] - clip_start)
        g_end = seconds_to_ass_time(group[-1]["end"] - clip_start)

        parts = []
        for word in group:
            ws = word["start"] - clip_start
            we = word["end"] - clip_start
            w_dur = int((we - ws) * 1000)
            # Highlight: scale up to 110% and turn yellow, then back
            parts.append(
                f"{{\\t({0},{w_dur},\\1c{YELLOW}&\\fscx110\\fscy110)"
                f"\\t({w_dur},{w_dur + 50},\\1c{WHITE}&\\fscx100\\fscy100)}}{word['text']} "
            )

        text = "".join(parts).strip()
        lines.append(f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


def _generate_minimal_clean_events(groups: list[list[dict]], clip_start: float) -> str:
    """Minimal Clean: Smooth fade in/out, subtle highlight."""
    lines = []
    for group in groups:
        g_start = seconds_to_ass_time(group[0]["start"] - clip_start)
        g_end = seconds_to_ass_time(group[-1]["end"] - clip_start)

        parts = []
        for word in group:
            ws = word["start"] - clip_start
            we = word["end"] - clip_start
            w_dur = int((we - ws) * 1000)
            parts.append(
                f"{{\\t(0,{w_dur},\\1c{CYAN}&)\\t({w_dur},{w_dur + 100},\\1c{WHITE}&)}}{word['text']} "
            )

        text = f"{{\\fad(200,200)}}" + "".join(parts).strip()
        lines.append(f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


def _generate_karaoke_sweep_events(groups: list[list[dict]], clip_start: float) -> str:
    """Karaoke Sweep: Words change from gray to white as spoken."""
    lines = []
    for group in groups:
        g_start = seconds_to_ass_time(group[0]["start"] - clip_start)
        g_end = seconds_to_ass_time(group[-1]["end"] - clip_start)

        parts = []
        for word in group:
            ws = word["start"] - clip_start
            we = word["end"] - clip_start
            w_dur = int((we - ws) * 1000)
            parts.append(
                f"{{\\1c{GRAY}&\\t(0,{w_dur},\\1c{WHITE}&)}}{word['text']} "
            )

        text = "".join(parts).strip()
        lines.append(f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


def _generate_bounce_in_events(groups: list[list[dict]], clip_start: float) -> str:
    """Bounce In: Words bounce in from below with stagger."""
    lines = []
    for group in groups:
        g_start = seconds_to_ass_time(group[0]["start"] - clip_start)
        g_end = seconds_to_ass_time(group[-1]["end"] - clip_start)

        parts = []
        for i, word in enumerate(group):
            delay = i * 80  # stagger
            # Start small and below, bounce up and scale
            parts.append(
                f"{{\\fscx50\\fscy50\\t({delay},{delay + 150},\\fscx115\\fscy115)"
                f"\\t({delay + 150},{delay + 250},\\fscx100\\fscy100)}}{word['text']} "
            )

        text = "".join(parts).strip()
        lines.append(f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


def _generate_glow_events(groups: list[list[dict]], clip_start: float) -> str:
    """Glow: Active word has brighter glow with pulse."""
    lines = []
    for group in groups:
        g_start = seconds_to_ass_time(group[0]["start"] - clip_start)
        g_end = seconds_to_ass_time(group[-1]["end"] - clip_start)

        parts = []
        for word in group:
            ws = word["start"] - clip_start
            we = word["end"] - clip_start
            w_dur = int((we - ws) * 1000)
            # Pulse outline during active word
            parts.append(
                f"{{\\bord3\\t(0,{w_dur // 2},\\bord6\\3c{CYAN}&)"
                f"\\t({w_dur // 2},{w_dur},\\bord3\\3c{WHITE}&)}}{word['text']} "
            )

        text = "".join(parts).strip()
        lines.append(f"Dialogue: 0,{g_start},{g_end},Default,,0,0,0,,{text}")

    return "\n".join(lines)


STYLE_GENERATORS = {
    "bold_pop": _generate_bold_pop_events,
    "minimal_clean": _generate_minimal_clean_events,
    "karaoke_sweep": _generate_karaoke_sweep_events,
    "bounce_in": _generate_bounce_in_events,
    "glow": _generate_glow_events,
}


def generate_captions(
    words: list[dict],
    clip_start: float,
    clip_end: float,
    style: str = "bold_pop",
    output_path: str = None,
    words_per_group: int = 5,
) -> str:
    """
    Generate animated ASS captions for a clip.

    Args:
        words: Word timestamps from transcription (absolute times)
        clip_start: Clip start time in source video
        clip_end: Clip end time in source video
        style: Caption style name
        output_path: Where to save the ASS file
        words_per_group: Words per subtitle block

    Returns:
        Path to generated ASS file
    """
    # Filter words within clip range
    clip_words = [
        w for w in words
        if w["start"] >= clip_start - 0.1 and w["end"] <= clip_end + 0.1
    ]

    if not clip_words:
        clip_words = [{"text": "...", "start": clip_start, "end": clip_start + 1}]

    groups = _group_words(clip_words, words_per_group)
    style_def = STYLE_DEFS.get(style, STYLE_DEFS["bold_pop"])
    generator = STYLE_GENERATORS.get(style, _generate_bold_pop_events)

    styles_block = style_def["style_line"]
    events_block = generator(groups, clip_start)

    ass_content = build_ass_file(styles_block, events_block)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

    return output_path or ass_content
