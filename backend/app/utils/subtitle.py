"""SRT and ASS subtitle format utilities."""


def seconds_to_srt_time(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_ass_time(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def generate_srt(word_timestamps: list[dict], words_per_group: int = 5) -> str:
    """Generate SRT from word timestamps."""
    groups = []
    for i in range(0, len(word_timestamps), words_per_group):
        group = word_timestamps[i:i + words_per_group]
        groups.append(group)

    lines = []
    for idx, group in enumerate(groups, 1):
        start = seconds_to_srt_time(group[0]["start"])
        end = seconds_to_srt_time(group[-1]["end"])
        text = " ".join(w["text"] for w in group)
        lines.append(f"{idx}\n{start} --> {end}\n{text}\n")

    return "\n".join(lines)


ASS_HEADER_TEMPLATE = """[Script Info]
Title: AutoClip Captions
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{styles}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
{events}"""


def build_ass_file(styles_block: str, events_block: str) -> str:
    """Build a complete ASS file from style and event blocks."""
    return ASS_HEADER_TEMPLATE.format(styles=styles_block, events=events_block)
