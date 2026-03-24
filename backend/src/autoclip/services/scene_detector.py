"""Scene detection using PySceneDetect."""
from scenedetect import detect, ContentDetector


def detect_scenes(video_path: str, threshold: float = 27.0) -> list[dict]:
    """
    Detect scene boundaries in video.
    Returns list of scenes with start/end timestamps.
    """
    scene_list = detect(video_path, ContentDetector(threshold=threshold))

    scenes = []
    for scene in scene_list:
        start_time = scene[0].get_seconds()
        end_time = scene[1].get_seconds()
        scenes.append({
            "start": round(start_time, 3),
            "end": round(end_time, 3),
            "duration": round(end_time - start_time, 3),
        })

    return scenes
