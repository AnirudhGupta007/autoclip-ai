"""Pexels music search integration."""
import httpx
from autoclip.config import PEXELS_API_KEY

PEXELS_AUDIO_URL = "https://api.pexels.com/videos/search"


async def search_music(query: str = "background music", per_page: int = 10) -> list[dict]:
    """
    Search Pexels for royalty-free music/audio.
    Note: Pexels primarily hosts videos. We search for short audio-visual content
    and extract audio URLs. For a production app, consider using a dedicated
    music API like Pixabay Audio or Freesound.
    """
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": query,
        "per_page": per_page,
        "size": "small",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(PEXELS_AUDIO_URL, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

    results = []
    for video in data.get("videos", []):
        # Get the smallest video file as audio source
        files = video.get("video_files", [])
        if not files:
            continue

        # Pick smallest file
        smallest = min(files, key=lambda f: f.get("width", 9999) * f.get("height", 9999))

        results.append({
            "id": str(video["id"]),
            "title": f"Pexels #{video['id']}",
            "duration": video.get("duration", 0),
            "preview_url": smallest.get("link", ""),
            "download_url": smallest.get("link", ""),
            "source": "pexels",
            "photographer": video.get("user", {}).get("name", "Unknown"),
        })

    return results
