# Frontend ↔ backend contract (chat history, usage, account)

The frontend (`src/services/api.js`) already calls these. All routes are under
`/api`, need the session cookie, and are scoped to the signed-in user: another
user's id returns **404**, not 403. Timestamps are ISO 8601 UTC strings.

The UI fails soft: if any of these 404s or errors, it shows an empty state and
the chat keeps working without history.

## Conversations

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/api/conversations` | – | `[{id, title, video_id, updated_at}]`, newest `updated_at` first |
| POST | `/api/conversations` | `{video_id?}` | `{id, title, video_id, updated_at}` (201 or 200) |
| GET | `/api/conversations/{id}/messages` | – | `[{id, role, content, clips, created_at}]`, oldest first |
| PATCH | `/api/conversations/{id}` | `{title}` | the updated conversation (body is not read by the UI) |
| DELETE | `/api/conversations/{id}` | – | 204 |

- `id`: string (UUID or short hex, the UI treats it as opaque).
- `video_id`: string or `null`.
- `title`: string. A new conversation may start as `""` or `"New chat"`; the
  server sets it to the first user prompt, truncated (~60 chars). The UI
  re-fetches the list after each turn to pick it up.
- `role`: `"user"` or `"assistant"`.
- `clips`: `null`, or an array of clip objects in the **same shape** the chat
  message endpoint already returns in `clips` (`id, title, file_url,
  thumbnail_url, duration, frame, start_time, end_time, overall_score, scores,
  style_tags, transcript`).
- Demo account: read-only for history. `PATCH`/`DELETE` should return 403 for
  it (the UI already hides rename/delete). `GET` and `POST` may work or 403;
  the UI copes with both.
- When the UI creates a conversation it is for the next message, so `POST`
  should not require a message.

## Chat (existing endpoints, one new optional field)

- `POST /api/chat/message` body gains `conversation_id?: string`:
  `{message, video_id, conversation_id?}`.
  - With it: use thread `u:{uid}:c:{cid}`, persist the user message and the
    assistant reply (`content` = `response`, `clips` = returned clips), bump
    `updated_at`, and set the title from the first prompt if still empty.
  - Without it: behave as today.
  - Unknown/foreign `conversation_id` → 404.
- `GET /api/chat/stream/{video_id}` accepts an optional query param
  `?conversation_id=…`. It may be ignored; events are unchanged.
- The UI creates a conversation (`POST /api/conversations`) before the first
  message of a new chat, then sends `conversation_id` on every message.

## Usage

`GET /api/me/usage` →

```json
{
  "queries_used": 1,
  "queries_limit": 2,
  "storage_bytes": 412000000,
  "storage_quota_bytes": 1610612736,
  "items": [
    {
      "video_id": "c2b0ab7cda68",
      "title": "episode-42.mp3",
      "media_kind": "audio",
      "size_bytes": 98000000,
      "source_expires_at": "2026-11-17T09:00:00Z",
      "clips_expire_at": "2026-12-10T09:00:00Z",
      "archived": false
    }
  ]
}
```

- `queries_limit: null` means unlimited (admins). The UI shows "Unlimited".
- `media_kind`: `"video"` or `"audio"`.
- `source_expires_at`: when the source file is deleted (upload + 7 days);
  `null` once archived.
- `clips_expire_at`: when the earliest remaining clip is deleted (render + 30
  days), or `null` if there are no clips.
- `archived`: `true` once the source file is gone.
- Optional, nice to have: the same `media_kind`, `source_expires_at`,
  `clips_expire_at`, `archived` fields on each item of `GET /api/videos`. The
  Library falls back to `/api/me/usage` if they're missing.
- Optional: `google_linked: bool` on `GET /api/auth/me`. Settings shows
  "Google: Not linked" until it exists.

## Account deletion

`DELETE /api/me` → 204. Deletes the user's files and rows, clears the
session cookie. The UI then refreshes `/api/auth/me` (expects 401) and goes
to `/`. The demo account should get 403; the UI hides the button for it.
