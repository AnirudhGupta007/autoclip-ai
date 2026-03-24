"""Audio analysis agent — extracts timeline of audio signals using librosa."""
import numpy as np
from pathlib import Path
from app.pipeline.state import PipelineState, AudioSignal


def run_audio_agent(state: PipelineState) -> dict:
    """
    Analyze audio features using librosa to detect energy, pace, and events.
    Produces a timeline of audio signals.
    """
    import librosa

    video_id = state["video_id"]
    audio_path = str(Path(f"outputs/{video_id}/audio.wav"))

    transcript_data = state.get("transcript_data", {})
    words = transcript_data.get("words", [])

    # Load audio
    try:
        y, sr = librosa.load(audio_path, sr=16000, mono=True)
    except Exception as e:
        print(f"Audio agent failed to load audio: {e}")
        return {"audio_timeline": []}

    duration = librosa.get_duration(y=y, sr=sr)

    # Compute features in 2-second windows
    window_sec = 2.0
    hop_samples = int(window_sec * sr)
    audio_timeline = []

    # RMS energy over time
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=512)
    rms_max = rms.max() if rms.max() > 0 else 1.0

    # Spectral centroid (correlates with brightness/excitement)
    spectral = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=512)[0]
    spectral_max = spectral.max() if spectral.max() > 0 else 1.0

    # Onset strength (detects sudden changes — laughter, applause, emphasis)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=512)
    onset_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=512)

    # Process in windows
    t = 0.0
    while t < duration:
        window_end = min(t + window_sec, duration)

        # Average RMS energy in this window
        mask = (rms_times >= t) & (rms_times < window_end)
        window_rms = rms[mask]
        energy = float(np.mean(window_rms) / rms_max) if len(window_rms) > 0 else 0.0

        # Average spectral centroid (pitch proxy)
        spec_mask = (rms_times >= t) & (rms_times < window_end)
        window_spec = spectral[spec_mask[:len(spectral)]] if spec_mask.sum() > 0 else np.array([0])
        pitch_change = float(np.std(window_spec) / spectral_max) if len(window_spec) > 1 else 0.0

        # Onset peaks in this window (detect events like laughter, applause)
        onset_mask = (onset_times >= t) & (onset_times < window_end)
        window_onsets = onset_env[onset_mask]
        onset_strength = float(np.mean(window_onsets)) if len(window_onsets) > 0 else 0.0

        # Count words in this window for speech pace
        window_words = [w for w in words if w["start"] >= t and w["end"] < window_end]
        word_count = len(window_words)
        speech_pace = word_count / window_sec * 60  # words per minute

        # Classify event type
        if word_count == 0 and energy < 0.1:
            event_type = "silence"
        elif word_count == 0 and energy > 0.3:
            event_type = "music"
        elif onset_strength > np.percentile(onset_env, 90) and word_count < 2:
            event_type = "laughter"  # high onset + few words = non-speech sound
        elif word_count == 0 and onset_strength > np.percentile(onset_env, 80):
            event_type = "applause"
        else:
            event_type = "speech"

        signal = AudioSignal(
            timestamp=round(t, 2),
            energy=min(1.0, energy),
            speech_pace=round(speech_pace, 1),
            event_type=event_type,
            pitch_change=min(1.0, pitch_change),
        )
        audio_timeline.append(signal)
        t += window_sec

    return {"audio_timeline": audio_timeline}
