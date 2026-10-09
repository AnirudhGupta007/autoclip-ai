# AutoClip eval · Wild Target (2010)

> copyrighted film — eval only, footage never published. Ground truth: 35 human-labelled moments, 6 ranked queries, film proper ends at 1:33:20 (duration 1:37:49).

`2026-10-01T12:36:19Z` · mode **from-results** · video `4cf75b3d8e2a` · runs **1** · git `9da3aad+dirty`

## Scoreboard

| Metric | Value | |
|---|---:|---|
| Query hit@3 | **0.00** | `░░░░░░░░░░` |
| Query hit@1 | **0.00** | `░░░░░░░░░░` |
| Query MRR | **0.00** | `░░░░░░░░░░` |
| Tag precision (clip ⊂ asked category) | **0.11** | `█▏░░░░░░░░` |
| Clip precision (clip ⊂ any human moment) | **0.22** | `██▎░░░░░░░` |
| Moment recall@all | **0.37** | `███▊░░░░░░` |
| Moment recall@25 | **0.17** | `█▊░░░░░░░░` |
| Moment precision@25 | **0.24** | `██▍░░░░░░░` |
| Length adherence (±10%) | **0.88** | `████████▊░` |
| Length adherence (±25%) | **1.00** | `██████████` |
| Aspect adherence | **1.00** | `██████████` |
| Transcript coverage (film minutes) | **0.03** | `▍░░░░░░░░░` |
| Analysed up to (fraction of film) | **1.00** | `██████████` |
| Moments in 2nd half of chunks (≈0.5 healthy) | **0.42** | `████▎░░░░░` |
| Clips with visible captions | **0.00** | `░░░░░░░░░░` |
| Duplicate clips | **0.00** | `░░░░░░░░░░` |
| Credits violations (clips+moments) | **0** |  |
| OpenRouter cost (USD) | **$1.449** |  |
| Wall time, all queries (s) | **1,291s** |  |

**Red flags**

- **Transcript covers 3/94 film minutes** (words only between 1:30:01 and 1:32:25) — most moments were found without dialogue, so 'one-liner'/'funny' asks are near-blind.
- 4 stretch(es) of 5+ minutes with no detected moment (35 min total): 30:32–43:10, 45:27–54:55, 1:14:31–1:20:30, 1:26:12–1:32:54.
- 5/54 analysis chunks failed: [17, 18, 19, 26, 53].
- Chat responses re-sent 30 previously produced clip(s) alongside the new one(s) — the UI shows the user clips they did not ask for.
- Delivered clips are on average 24% black bars (cropdetect) — the film's letterbox survives reframing, so vertical clips waste that share of the frame on black.
- No delivered clip has visible burned-in captions (bottom-third diff vs the pre-caption render).
- 4 clip(s) were rendered during analysis that nobody asked for (not returned to the user; wasted render time).

## Per query

| Query | Asked | Clips | hit@1 | hit@3 | MRR | Best truth rank | Tag prec. | Len ±10% | Aspect | Time | Cost |
|---|---|---:|:-:|:-:|---:|:-:|---:|:-:|:-:|---:|---:|
| **q_funny** — funniest moment | ×4 · 30s · 9:16 | 4 | ✗ | ✗ | 0.00 | – | 0.25 | 1.00 | 1.00 | 1,118s | $1.445 |
| **q_action** — an action scene | 45s · 16:9 | 1 (+4 stale) | ✗ | ✗ | 0.00 | – | 0.00 | 1.00 | 1.00 | 19s | $0.000 |
| **q_tense** — the most tense moment | 20s · 1:1 | 1 (+5 stale) | ✗ | ✗ | 0.00 | – | 0.00 | 0.00 | 1.00 | 22s | $0.000 |
| **q_emotional** — an emotional or romantic moment | 30s | 1 (+6 stale) | ✗ | ✗ | 0.00 | – | 0.00 | 1.00 | – | 53s | $0.002 |
| **q_shot_at** — a clip where someone gets shot at | – | 1 (+7 stale) | ✗ | ✗ | 0.00 | – | 0.00 | – | – | 51s | $0.001 |
| **q_one_liner** — the best one-liner | 15s | 1 (+8 stale) | ✗ | ✗ | 0.00 | – | 0.00 | 1.00 | – | 28s | $0.001 |

<details><summary>Human truth per query</summary>

- **q_funny** (funny): 1. `m18` 48:32–49:22 Victor's absurd apprenticeship offer to Tony, 2. `m22` 1:00:12–1:01:12 Victor awkwardly asks bath-bound Tony if he is confusing him, 3. `m26` 1:12:20–1:13:05 Dixon's goon demands the dead painter's address
- **q_action** (action): 1. `m16` 45:20–46:20 Red Mini car chase through the City with gunfire, 2. `m15` 43:05–44:00 Mike tries to drown Tony; Tony shoots his ear off, 3. `m06` 20:58–21:58 Car-park ambush in Rose's Mini; shots fired, Tony grabs a gun and fires
- **q_tense** (tense): 1. `m32` 1:30:00–1:30:50 Dixon orders Victor to kill Rose; he turns and shoots instead, 2. `m06` 20:58–21:58 Car-park ambush in Rose's Mini; shots fired, Tony grabs a gun and fires, 3. `m30` 1:22:05–1:22:55 Rose holds them at gunpoint: liar, killer, thief - made for each other
- **q_emotional** (emotional, romantic): 1. `m23` 1:04:40–1:05:40 Late-night foot massage; Rose admits she likes being protected, 2. `m29` 1:19:20–1:20:15 Rose finds the scrapbook with her own photo crossed out, 3. `m25` 1:09:40–1:10:40 Rose in Tony's bed admits she loves Victor
- **q_shot_at** (shot_at): 1. `m06` 20:58–21:58 Car-park ambush in Rose's Mini; shots fired, Tony grabs a gun and fires, 2. `m15` 43:05–44:00 Mike tries to drown Tony; Tony shoots his ear off, 3. `m34` 1:31:30–1:32:10 Dixon's old borrowed gun backfires and kills him
- **q_one_liner** (one_liner): 1. `m03` 10:28–11:12 Rose, in disguise, haggles Ferguson up to a million, 2. `m30` 1:22:05–1:22:55 Rose holds them at gunpoint: liar, killer, thief - made for each other, 3. `m34` 1:31:30–1:32:10 Dixon's old borrowed gun backfires and kills him

</details>

## Per clip

| # | Clip | Query | Title (app) | Span | Len asked→got | Frame asked→got | Human moment | Cat. | Capt. | Black bars |
|---:|---|---|---|---|---|---|---|:-:|:-:|---:|
| 1 | `7893c88f8fec` | q_funny | Calm Walk Past a Fallen Body | 1:28–1:58 | 30→30.8s ✓ | 9:16→1080x1920 ✓ | `m01` Victor's deadpan French-tape lesson: he is a professional assassin *(funny, one_liner)* | ✓ | ✗ | 24% |
| 2 | `b2d7e1134105` | q_funny | Gun Turn: Parrot's Gaze | 2:59–3:29 | 30→32.1s ✓ | 9:16→1080x1920 ✓ | — none | ✗ | ✗ | 24% |
| 3 | `66880b36d78e` | q_funny | Fall to the Ground | 22:52–23:22 | 30→31.3s ✓ | 9:16→1080x1920 ✓ | — none | ✗ | ✗ | 24% |
| 4 | `a3cca993fd30` | q_funny | Grateful Moment, Cut Short | 1:04:32–1:05:02 | 30→30.9s ✓ | 9:16→1080x1920 ✓ | `m23` Late-night foot massage; Rose admits she likes being protected *(romantic)* | ✗ | ✗ | 24% |
| 5 | `803e19f8ef20` | q_action | Pick Up the Gun—Find Him Now | 1:02:16–1:03:02 | 45→46.1s ✓ | 16:9→1280x720 ✓ | — none | ✗ | ✗ | 25% |
| 6 | `7f81288706ce` | q_tense | Dramatic Escape Through Broken Window | 1:21:04–1:21:24 | 20→22.8s ✗ | 1:1→1080x1080 ✓ | — none | ✗ | ✗ | 24% |
| 7 | `7ff56a886204` | q_emotional | Guns Down, Touch Lost – Game Over | 10:10–10:40 | 30→30.3s ✓ | –→1080x1920 – | — none | ✗ | ✗ | 24% |
| 8 | `3e6fc85fca51` | q_shot_at | Cat's Out of the Bag: Clean Your Weapon! | 7:48–8:18 | –→31.5s – | –→1080x1920 – | — none | ✗ | ✗ | 24% |
| 9 | `992162eb0f9c` | q_one_liner | I Choose, I Chose, I Have Chosen | 1:26:00–1:26:14 | 15→16.4s ✓ | –→1080x1920 – | — none | ✗ | ✗ | 24% |

Not requested (rendered during analysis, never returned): `9e6bf240fb23` 16:30–17:00, `023e6f31cea2` 19:04–19:34, `b5cac5d8c852` 3:59–4:29 ≈ `m02`, `72716b52e3b2` 1:10:54–1:11:24

## Moment detection

52 fused moments in the DB, ranked by convergence score.

| k | recall@k | precision@k |
|---|---:|---:|
| 10 | 0.09 `▉░░░░░░░░░` | 0.30 |
| 25 | 0.17 `█▊░░░░░░░░` | 0.24 |
| all | 0.37 `███▊░░░░░░` | 0.25 |

**Recall by tenth of the film** (human moments bucketed by midpoint; right column = system moments in that tenth)

```
tenth  span            human  found  recall              system
   1      0:00–9:20        2      2  ██████████ 1.00   ████████████ 15
   2      9:20–18:40       2      1  █████░░░░░ 0.50   ████████▊░░░ 11
   3     18:40–28:00       5      2  ████░░░░░░ 0.40   █████▋░░░░░░ 7
   4     28:00–37:20       3      0  ░░░░░░░░░░ 0.00   █▋░░░░░░░░░░ 2
   5     37:20–46:40       4      2  █████░░░░░ 0.50   █▋░░░░░░░░░░ 2
   6     46:40–56:00       4      2  █████░░░░░ 0.50   █▋░░░░░░░░░░ 2
   7     56:00–1:05:20     3      1  ███▍░░░░░░ 0.33   ███▎░░░░░░░░ 4
   8   1:05:20–1:14:40     4      2  █████░░░░░ 0.50   ██▍░░░░░░░░░ 3
   9   1:14:40–1:24:00     3      0  ░░░░░░░░░░ 0.00   ███▎░░░░░░░░ 4
  10   1:24:00–1:33:20     5      1  ██░░░░░░░░ 0.20   █▋░░░░░░░░░░ 2
```

**Where in each 120s analysis chunk moments are found** (229 moments; source: raw per-chunk moments (SSE), exact chunk index). Flat is healthy; a cliff after ~60s means the tail of each chunk is not being looked at.

```
   0–20  s  ███████░░░░░░░░░░░░░░░░░ 17
  20–40  s  ███████████████████████▋ 57
  40–60  s  ████████████████████████ 58
  60–80  s  ███████████████▊░░░░░░░░ 38
  80–100 s  ██████████████▌░░░░░░░░░ 35
 100–120 s  █████████▉░░░░░░░░░░░░░░ 24
```

<details><summary>Human moments with no matching system moment (22)</summary>

- `m04` 12:25–13:10 *funny* — Ferguson gloats over his Rembrandt, then sees it is a fake
- `m05` 19:25–19:55 *dialogue* — Mother scolds Victor for sparing Rose
- `m07` 22:00–22:45 *funny* — Nervous Tony holds the gun on Victor
- `m09` 27:25–28:25 *action, funny* — Escape from the car park; crash, Tony lands on the windscreen
- `m10` 28:32–29:25 *funny* — Hotel check-in as Smith, Smith and Tony; one room
- `m11` 33:30–34:30 *romantic* — Hotel bar: Rose flirts with the barman and orders a huge round
- `m12` 36:00–36:52 *tense* — Ferguson's quietly menacing speech to Mike
- `m13` 40:12–41:00 *funny, one_liner* — Ferguson hires rival hitman Dixon, who names Victor from a vague description
- `m14` 42:08–43:08 *tense, action* — Mike sneaks into the suite with a gun and finds Tony in the bath
- `m17` 46:20–47:12 *action* — Chase climax: pram near-miss, pursuers crash
- `m18` 48:32–49:22 *funny* — Victor's absurd apprenticeship offer to Tony
- `m21` 57:30–58:30 *emotional, one_liner* — Garden row: Rose attacks Victor's over-careful life
- `m22` 1:00:12–1:01:12 *funny* — Victor awkwardly asks bath-bound Tony if he is confusing him
- `m25` 1:09:40–1:10:40 *romantic* — Rose in Tony's bed admits she loves Victor
- `m26` 1:12:20–1:13:05 *funny* — Dixon's goon demands the dead painter's address
- `m28` 1:16:15–1:17:10 *romantic* — Victor and Rose in bed on his birthday
- `m29` 1:19:20–1:20:15 *emotional, tense* — Rose finds the scrapbook with her own photo crossed out
- `m30` 1:22:05–1:22:55 *dialogue, tense, one_liner* — Rose holds them at gunpoint: liar, killer, thief - made for each other
- `m31` 1:27:00–1:27:50 *funny* — Barn shooting practice; Tony is a natural
- `m32` 1:30:00–1:30:50 *tense, shot_at, romantic, action* — Dixon orders Victor to kill Rose; he turns and shoots instead
- `m33` 1:30:50–1:31:30 *funny, one_liner, action* — Victor's mother arrives armed to save the day
- `m34` 1:31:30–1:32:10 *action, shot_at, funny, one_liner* — Dixon's old borrowed gun backfires and kills him

</details>

**Transcript:** 3/94 film minutes contain at least one word (482 words, first at 1:30:01, last at 1:32:25).

## How these numbers are computed

- **Match rule:** a clip/moment matches a human moment iff they overlap by ≥ 50% of the *shorter* of the two.
- **hit@k / MRR:** the query's delivered clips, in delivery order, against the human's top-3 truth for that query (relevant = matches any of the three). *Best truth rank* = the best of the human's ranks that any clip hit.
- **Tag precision:** share of delivered clips that match *any* human moment carrying one of the asked tags (e.g. any `funny` moment, not just the top 3). **Clip precision:** share matching any human moment at all.
- **Moment recall/precision@k:** DB moments ranked by convergence score, one-to-one greedy matching by tIoU.
- **Length adherence:** |delivered − asked| ≤ 10% (and ≤ 25%) of asked, from ffprobe; queries that didn't specify a length/frame are excluded from that column.
- **Captions:** mean |final − reframed| pixel difference in the bottom third at 4 timestamps (≥ 2/255 = visible). **Black bars:** ffmpeg `cropdetect` on 3 windows.
- **Cost:** OpenRouter `/credits` usage delta (lags a few seconds; per-query values are indicative, totals reliable).
