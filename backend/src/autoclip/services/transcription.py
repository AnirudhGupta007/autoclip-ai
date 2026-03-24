"""AssemblyAI transcription service with word-level timestamps."""
import assemblyai as aai
from autoclip.config import ASSEMBLYAI_API_KEY

aai.settings.api_key = ASSEMBLYAI_API_KEY


def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribe audio file using AssemblyAI.
    Returns transcript text, word timestamps, and utterances.
    """
    config = aai.TranscriptionConfig(
        speech_model=aai.SpeechModel.best,
        speaker_labels=True,
    )

    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_path, config=config)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"Transcription failed: {transcript.error}")

    words = []
    for word in transcript.words:
        words.append({
            "text": word.text,
            "start": word.start / 1000.0,
            "end": word.end / 1000.0,
            "confidence": word.confidence,
            "speaker": word.speaker,
        })

    utterances = []
    if transcript.utterances:
        for utt in transcript.utterances:
            utterances.append({
                "speaker": utt.speaker,
                "text": utt.text,
                "start": utt.start / 1000.0,
                "end": utt.end / 1000.0,
            })

    return {
        "text": transcript.text,
        "words": words,
        "utterances": utterances,
    }
