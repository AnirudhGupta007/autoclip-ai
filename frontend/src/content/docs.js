/*
 * Content for /docs. Plain data, rendered by pages/Docs.jsx — no markdown
 * dependency. Inline text supports `code` and [label](url).
 *
 * Block types: { p }, { ul: [...] }, { ol: [...] }, { h }, { dl: [[term, def]] },
 * { faq: [[question, answer]] }, { note }.
 *
 * Keep the numbers here in step with the backend config (limits, retention).
 */

export const REPO = 'https://github.com/AnirudhGupta007/autoclip-ai'
export const UPDATED = '10 November 2026'

export const LIMITS = {
  minutes: 60,
  uploadMb: 300,
  queriesPerDay: 2,
  uploads: 3,
  storageGb: 1.5,
  sourceDays: 7,
  clipDays: 30,
  inactiveDays: 60,
}

export const SECTIONS = [
  {
    id: 'how-it-works',
    title: 'How it works',
    blocks: [
      {
        p: 'You upload a podcast or video, up to an hour long. AutoClip analyses it once, in the background. After that, every chat request is a search over what it found, followed by an ffmpeg cut, so later requests come back in seconds.',
      },
      { h: 'The pipeline' },
      {
        ol: [
          'Upload. The file is stored and a background analysis job starts. Progress streams to the browser over Server-Sent Events.',
          'Audio becomes an audiogram. An audio-only upload (MP3, M4A, WAV, AAC, OGG, FLAC) is turned into a video once, at upload time: a waveform and the episode title on black. Everything after this step treats it like any other video, and the clips come out as captioned audiograms.',
          'Transcription. The audio is split into short segments and transcribed in parallel through OpenRouter (Gemini 2.5 Flash-Lite), with phrase-level timestamps.',
          'Window analysis. The source is cut into 2-minute windows with a 10-second overlap. For each window a vision model reads sampled frames together with that window’s transcript and writes up to five moments. Audio uploads skip vision completely and use the transcript only. On static-camera video, such as two people at a podcast desk, fewer frames are sent, because more frames add cost without adding information.',
          'Fusion. Moments that overlap in time are merged and near-duplicates are dropped.',
          'Indexing. Each moment is embedded and stored in Postgres with pgvector.',
          'Your request. A LangGraph agent reads what you asked for, retrieves candidate moments, and calls the tools that cut, reframe, caption and score the clips.',
        ],
      },
      { h: 'The multimodal RAG, exactly' },
      {
        p: 'The unit that gets indexed is a fused moment: the vision model’s description of what happens, plus the dialogue spoken during it. That text is embedded with `bge-m3` (1024 dimensions). There is no separate image index. On a podcast the visuals barely change, so quality rests mostly on the dialogue.',
      },
      {
        ul: [
          'Candidates come from three lists merged round-robin: vector similarity to your request (top 25), category tags such as funny, insight, hot take, story, quotable or advice (top 25), and keyword matches (top 10).',
          'One LLM call (Gemini 2.5 Flash) re-ranks those candidates against what you actually asked for.',
          'A diversity filter removes clips that overlap each other, so you don’t get the same 30 seconds three times.',
          'The agent is not allowed to describe a clip that a tool did not return in that turn.',
        ],
      },
      {
        note: 'Honest weak spot: the right moment is usually found, but ranking it first for a very specific request is still modest. EVALUATION.md in the repo has the measured numbers.',
      },
    ],
  },
  {
    id: 'limits',
    title: 'Limits',
    blocks: [
      { p: 'This is a portfolio project that one person pays for, so the limits are small on purpose.' },
      {
        dl: [
          ['Length', `Up to ${LIMITS.minutes} minutes per upload.`],
          ['File size', `${LIMITS.uploadMb} MB per upload.`],
          ['Requests', `${LIMITS.queriesPerDay} agent requests per day per account. A failed request is refunded.`],
          ['Uploads', `${LIMITS.uploads} stored uploads at a time. Delete one from the Library to make room.`],
          ['Formats', 'Video: MP4, MOV, MKV, WEBM. Audio: MP3, M4A, WAV, AAC, OGG, FLAC.'],
          ['Demo', 'The shared demo account is read-only: it can chat about pre-analysed videos but cannot upload, rename or delete.'],
        ],
      },
    ],
  },
  {
    id: 'storage',
    title: 'Storage rules',
    blocks: [
      {
        p: 'The server has a small disk, so files don’t live forever. Settings shows your usage and the date each item will be deleted.',
      },
      {
        dl: [
          ['Quota', `${LIMITS.storageGb} GB per account, counting source files and rendered clips.`],
          [
            'Source file',
            `Deleted ${LIMITS.sourceDays} days after upload. The transcript, moments, chats and clips stay. The item is then “archived”: old clips still play, but new clips need a fresh upload.`,
          ],
          ['Clips', `Deleted ${LIMITS.clipDays} days after they were rendered. Download the ones you want to keep.`],
          ['Inactive accounts', `After ${LIMITS.inactiveDays} days without a sign-in, all files are deleted. The account itself is kept.`],
          ['Full disk', 'If the server is nearly full, new uploads are refused until space frees up.'],
        ],
      },
    ],
  },
  {
    id: 'faq',
    title: 'FAQ',
    blocks: [
      {
        faq: [
          ['Can I upload something longer than an hour?', 'Not here. Split it into parts of an hour or less and upload them separately. The self-hosted version has no such cap if you change the config.'],
          ['Does it work on audio-only podcasts?', 'Yes. The audio becomes an audiogram video at upload, analysis uses the transcript only, and the clips come back as captioned audiograms.'],
          ['Why only two requests a day?', 'Each request runs real model calls that cost money, and this project has no revenue. The analysis of each upload is shared by every request after it, so ask for several clips in one request.'],
          ['How long does analysis take?', 'About 10 to 15 minutes for an hour-long upload; the studio shows a live estimate. You can leave the tab open: your first request finishes automatically when analysis is done.'],
          ['Who can see my uploads?', 'Only you. Every video, chat and clip is tied to your account, and that is checked on every route and inside the agent’s tools.'],
          ['Are my files used to train models?', 'This project trains nothing. Audio, frames and text are sent to AI models through OpenRouter to be processed; see the privacy policy below.'],
          ['How do I delete everything?', 'Settings → Delete account. It removes your files and your account’s rows.'],
        ],
      },
    ],
  },
  {
    id: 'privacy',
    title: 'Privacy policy',
    blocks: [
      {
        p: `Last updated ${UPDATED}. AutoClip is a personal portfolio project run by one developer. It is not a company and does not sell anything. This page says plainly what happens to your data.`,
      },
      { h: 'What is stored' },
      {
        ul: [
          'Your account: email address, and a password hash (argon2) if you use a password. If you sign in with Google, your Google account ID and email.',
          'What you upload, and what is made from it: transcripts, detected moments, chat messages and rendered clips.',
          'Usage counts (requests per day, storage used) and a session record.',
          'Daily request counters per IP address, used for rate limiting and kept for about a day.',
          'Standard server logs (IP address, time, request path), kept for debugging and abuse prevention.',
        ],
      },
      { h: 'Who else sees it' },
      {
        ul: [
          'To analyse your upload, its audio, sampled frames and text are sent to AI models through OpenRouter, which routes them to model providers such as Google. Their own data policies apply to that processing.',
          'Nothing is sold, shared for advertising or used to train models by this project.',
          'There are no analytics or advertising trackers on this site.',
          'Fonts, scripts and every other asset are served from this server, so your browser makes no requests to Google Fonts, CDNs or other third parties. The only third parties that receive your data are OpenRouter and the model providers it routes to.',
        ],
      },
      { h: 'Where and how long' },
      {
        ul: [
          'Everything is stored on one AWS server in Mumbai (ap-south-1).',
          'Files are deleted on the schedule in Storage rules above. Deleting your account removes your files and your data from the database. Backups, if any, roll over within a few days.',
        ],
      },
      { h: 'Cookies' },
      { p: 'One httpOnly session cookie that keeps you signed in. No tracking cookies.' },
      { h: 'Contact' },
      { p: `Questions or deletion requests: open an issue on [GitHub](${REPO}/issues).` },
    ],
  },
  {
    id: 'terms',
    title: 'Terms of use',
    blocks: [
      { p: `Last updated ${UPDATED}. By using AutoClip you agree to these terms.` },
      {
        ul: [
          'It is a free demo, provided as is, with no warranty. It may be slow, go offline, lose data or be reset at any time.',
          'Upload only content you own or have the rights to use. Nothing illegal, nothing that infringes someone else’s rights.',
          'Don’t try to get around the limits, overload the server or access other people’s data.',
          'You keep all rights to your content. You allow AutoClip to process it only to make your clips.',
          'Accounts that break these terms may be removed.',
          'To the extent the law allows, the developer is not liable for any loss from using the service.',
          `The source code is MIT-licensed; see the [repository](${REPO}).`,
        ],
      },
    ],
  },
  {
    id: 'self-host',
    title: 'Self-host it',
    blocks: [
      {
        p: `The whole thing is open source. You need Docker and an OpenRouter API key. Your own instance has your own limits.`,
      },
      {
        ol: [
          `Clone the [repository](${REPO}).`,
          'Copy `.env.example` to `.env` and set `OPENROUTER_API_KEY`.',
          'Run `docker compose up -d`.',
          'Open `http://localhost` and sign up.',
        ],
      },
      { p: `The README covers the architecture and environment variables, and DEPLOY.md covers running it on a single EC2 box.` },
    ],
  },
]
