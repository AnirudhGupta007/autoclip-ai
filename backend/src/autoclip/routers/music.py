"""Music search endpoint using Pexels."""
from fastapi import APIRouter, Depends, Query
from autoclip.auth.deps import current_user
from autoclip.services.music_service import search_music

router = APIRouter(prefix="/api/music", tags=["music"], dependencies=[Depends(current_user)])


@router.get("/search")
async def search(
    q: str = Query("background music", description="Search query"),
    mood: str = Query(None, description="Mood filter"),
    per_page: int = Query(10, ge=1, le=30),
):
    """Search for royalty-free music."""
    query = q
    if mood:
        query = f"{mood} {q}"

    results = await search_music(query=query, per_page=per_page)
    return {"results": results, "count": len(results)}
