"""Audio analysis agent — extracts timeline of audio signals using librosa.

Extracts multiple audio features in sliding windows:
    - RMS energy (volume)
    - Spectral centroid (brightness/excitement proxy)
    - Spectral rolloff (frequency distribution)
    - Zero crossing rate (noisiness)
    - Onset strength (transient events — laughter, applause, emphasis)
    - Tempo estimation per window
    - Speech pace from word timestamps
    - Event classification (speech, laughter, applause, silence, music)

The combination of these features creates a rich audio fingerprint
that the fusion node uses alongside visual and text signals.
"""
import numpy as np
from pathlib import Path
from autoclip.pipeline.state import PipelineState, AudioSignal


# ─── Audio feature extraction configuration ───────────────────

WINDOW_SEC = 2.0        # Analysis window size in seconds
HOP_LENGTH = 512        # librosa hop length for feature extraction
SAMPLE_RATE = 16000     # Audio sample rate (matches transcription extraction)
FRAME_LENGTH = 2048     # FFT window size

# Event detection thresholds (calibrated empirically)
SILENCE_ENERGY_THRESHOLD = 0.05     # Below this = silence
MUSIC_ENERGY_THRESHOLD = 0.3        # High energy + no speech = music
HIGH_SPEECH_PACE = 180              # Words per minute threshold for "fast"
ONSET_PERCENTILE = 85               # Top percentile for onset events


def _compute_rms_features(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute RMS energy and corresponding timestamps."""
    import librosa
    rms = librosa.feature.rms(y=y, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=HOP_LENGTH)
    return rms, times


def _compute_spectral_features(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Compute spectral centroid, rolloff, and zero crossing rate."""
    import librosa
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=HOP_LENGTH)[0]
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, hop_length=HOP_LENGTH)[0]
    zcr = librosa.feature.zero_crossing_rate(y, frame_length=FRAME_LENGTH, hop_length=HOP_LENGTH)[0]
    return centroid, rolloff, zcr


def _compute_onset_features(y: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray]:
    """Compute onset strength envelope — detects transient events."""
    import librosa
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP_LENGTH)
    onset_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=HOP_LENGTH)
    return onset_env, onset_times


def _estimate_local_tempo(onset_env: np.ndarray, sr: int, start_frame: int, end_frame: int) -> float:
    """Estimate tempo in a local window from onset envelope."""
    import librosa
    segment = onset_env[start_frame:end_frame]
    if len(segment) < 10:
        return 0.0
    try:
        tempo = librosa.beat.tempo(onset_envelope=segment, sr=sr, hop_length=HOP_LENGTH)
        return float(tempo[0]) if len(tempo) > 0 else 0.0
    except Exception:
        return 0.0


def _get_window_indices(times: np.ndarray, window_start: float, window_end: float) -> np.ndarray:
    """Get boolean mask for frames within a time window."""
    return (times >= window_start) & (times < window_end)


def _classify_audio_event(
    energy: float,
    word_count: int,
    onset_strength: float,
    onset_threshold: float,
    zcr_mean: float,
    window_sec: float,
) -> str:
    """Classify the dominant audio event in a window.

    Classification logic:
        - silence: very low energy + no words
        - music: moderate+ energy + no words + low ZCR (tonal)
        - laughter: high onset + few words + high ZCR (noisy)
        - applause: high onset + no words + very high ZCR
        - speech: has words
    """
    if word_count == 0 and energy < SILENCE_ENERGY_THRESHOLD:
        return "silence"

    if word_count == 0 and energy > MUSIC_ENERGY_THRESHOLD and zcr_mean < 0.1:
        return "music"

    if onset_strength > onset_threshold and word_count < 2:
        if zcr_mean > 0.15:
            return "applause"
        return "laughter"

    if word_count > 0:
        return "speech"

    return "silence"


def _compute_pitch_variability(centroid: np.ndarray, mask: np.ndarray, max_centroid: float) -> float:
    """Compute pitch variability as normalized standard deviation of spectral centroid."""
    window_centroid = centroid[mask[:len(centroid)]] if mask.sum() > 0 else np.array([0])
    if len(window_centroid) < 2 or max_centroid == 0:
        return 0.0
    return min(1.0, float(np.std(window_centroid) / max_centroid))


def run_audio_agent(state: PipelineState) -> dict:
    """Extract multi-feature audio timeline using librosa.

    Process:
        1. Load audio file
        2. Compute global features: RMS, spectral, onset
        3. Slide 2-second windows across audio
        4. For each window: aggregate features, count words, classify event
        5. Return timeline of AudioSignal dataclasses
    """
    import librosa

    video_id = state["video_id"]
    audio_path = str(Path(f"outputs/{video_id}/audio.wav"))
    transcript_data = state.get("transcript_data", {})
    words = transcript_data.get("words", [])

    # Load audio
    try:
        y, sr = librosa.load(audio_path, sr=SAMPLE_RATE, mono=True)
    except Exception as e:
        print(f"Audio agent failed to load audio: {e}")
        return {"audio_timeline": []}

    duration = librosa.get_duration(y=y, sr=sr)

    # ─── Compute global features ──────────────────────────────
    rms, rms_times = _compute_rms_features(y, sr)
    centroid, rolloff, zcr = _compute_spectral_features(y, sr)
    onset_env, onset_times = _compute_onset_features(y, sr)

    # Normalization denominators (avoid division by zero)
    rms_max = rms.max() if rms.max() > 0 else 1.0
    centroid_max = centroid.max() if centroid.max() > 0 else 1.0
    onset_threshold = np.percentile(onset_env, ONSET_PERCENTILE) if len(onset_env) > 0 else 1.0

    # ─── Sliding window analysis ──────────────────────────────
    audio_timeline = []
    t = 0.0

    while t < duration:
        window_end = min(t + WINDOW_SEC, duration)

        # RMS energy in window
        rms_mask = _get_window_indices(rms_times, t, window_end)
        window_rms = rms[rms_mask]
        energy = float(np.mean(window_rms) / rms_max) if len(window_rms) > 0 else 0.0
        rms_db = float(20 * np.log10(np.mean(window_rms) + 1e-10)) if len(window_rms) > 0 else -80.0

        # Spectral centroid (pitch/brightness proxy)
        spec_mask = _get_window_indices(rms_times, t, window_end)
        window_centroid = centroid[spec_mask[:len(centroid)]] if spec_mask.sum() > 0 else np.array([0])
        spectral_centroid_mean = float(np.mean(window_centroid) / centroid_max) if len(window_centroid) > 0 else 0.0

        # Pitch variability
        pitch_change = _compute_pitch_variability(centroid, spec_mask, centroid_max)

        # Zero crossing rate (noisiness)
        window_zcr = zcr[spec_mask[:len(zcr)]] if spec_mask.sum() > 0 else np.array([0])
        zcr_mean = float(np.mean(window_zcr)) if len(window_zcr) > 0 else 0.0

        # Onset strength (transient events)
        onset_mask = _get_window_indices(onset_times, t, window_end)
        window_onsets = onset_env[onset_mask]
        onset_mean = float(np.mean(window_onsets)) if len(window_onsets) > 0 else 0.0

        # Local tempo estimation
        start_frame = int(t * sr / HOP_LENGTH)
        end_frame = int(window_end * sr / HOP_LENGTH)
        local_tempo = _estimate_local_tempo(onset_env, sr, start_frame, end_frame)

        # Speech pace from word timestamps
        window_words = [w for w in words if w["start"] >= t and w["end"] < window_end]
        word_count = len(window_words)
        speech_pace = word_count / WINDOW_SEC * 60  # words per minute

        # Event classification
        event_type = _classify_audio_event(
            energy, word_count, onset_mean, onset_threshold, zcr_mean, WINDOW_SEC
        )

        signal = AudioSignal(
            timestamp=round(t, 2),
            energy=min(1.0, energy),
            speech_pace=round(speech_pace, 1),
            event_type=event_type,
            pitch_change=min(1.0, pitch_change),
            rms_db=round(rms_db, 1),
            spectral_centroid=round(spectral_centroid_mean, 4),
            tempo_local=round(local_tempo, 1),
        )
        audio_timeline.append(signal)
        t += WINDOW_SEC

    return {"audio_timeline": audio_timeline}
