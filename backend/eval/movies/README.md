# Eval benchmarks

Human ground truth for scoring AutoClip on long videos. Each `<slug>.json` has the
same schema: video metadata, `chunking`, `labeling` notes, `moments` (clip-worthy
windows with `start`/`end` seconds, `tags`, `grade` 1-3, `note`) and `queries`
(user prompts with `count`/`length`/`frame`, the tags that answer them, and a
ranked top-3 `truth` of moment ids). Grade 3 = in some query's truth, 2 = solid
standalone clip, 1 = needs context. Video files are never stored in this repo.

| slug | video | length | licence | may clips be published? |
|---|---|---|---|---|
| `wild_target` | *Wild Target* (2010), feature film | 97.8 min | copyrighted | **No.** Eval only; footage and clips must never be published or committed. |
| `doctorow_39c3` | Cory Doctorow, "A post-American, enshittification-resistant internet", 39C3 talk + Q&A | 61.2 min | CC BY 4.0 | **Yes**, with attribution (see below). |

## wild_target

Comedy/action film: 35 moments, 6 queries (funny, action, tense, emotional,
shot_at, one-liner). `wild_target_baseline/` holds a scored baseline run.
Copyrighted - use only for local evaluation.

## doctorow_39c3

Single energetic speaker on stage with collage slides, then audience Q&A
(~52:00-61:00). 34 moments tagged funny / quotable / insightful / controversial /
heated / story / emotional, plus topic tags `enshittification` and `ai`;
6 queries (funniest x3 at 30s 9:16, most insightful 45s, heated rant 30s 1:1,
great story 60s 16:9, best quote 15s, a moment about enshittification).

- Source: https://media.ccc.de/v/39c3-a-post-american-enshittification-resistant-internet
  (page states "Licensed to the public under http://creativecommons.org/licenses/by/4.0")
- Local file: `~/Videos/autoclip-bench/doctorow_39c3.mp4` (720p H.264 transcode of the
  1080p English-only `39c3-1421-eng-...mp4` from cdn.media.ccc.de)
- Attribution to show with any published clip (also in the JSON `attribution` field):
  > Cory Doctorow, "A post-American, enshittification-resistant internet", 39C3
  > (Chaos Communication Congress, Hamburg, Dec 2025). Recording via media.ccc.de,
  > licensed CC BY 4.0. Clips trimmed/reframed.
- The projected slides are Doctorow's collages built from CC BY / CC BY-SA images
  (credits are shown on screen); prefer speaker-only crops for published clips, or keep
  the on-screen credits.
