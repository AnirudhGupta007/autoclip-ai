"""Markdown + CSV rendering for eval_movie reports."""
from __future__ import annotations

import csv
import io
from typing import Optional

from .score import HEADLINE

BLOCKS = " ▏▎▍▌▋▊▉█"


def bar(frac: Optional[float], width: int = 10) -> str:
    """Unicode progress bar, eighth-block resolution."""
    if frac is None:
        return "·" * width
    frac = max(0.0, min(1.0, frac))
    full, rem = divmod(round(frac * width * 8), 8)
    s = "█" * full + (BLOCKS[rem] if rem and full < width else "")
    return s + "░" * (width - len(s))


def mmss(t: Optional[float]) -> str:
    if t is None:
        return "–"
    t = int(round(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def fmt(v, kind: str = "rate") -> str:
    if v is None:
        return "–"
    if kind == "rate":
        return f"{v:.2f}"
    if kind == "usd":
        return f"-${abs(v):.3f}" if v < 0 else f"${v:.3f}"
    if kind == "secs":
        return f"{v:,.0f}s"
    if kind == "count":
        return f"{v:g}"
    return str(v)


def yn(v) -> str:
    return "–" if v is None else ("✓" if v else "✗")


def _esc(s) -> str:
    return str(s if s is not None else "").replace("|", "\\|").replace("\n", " ")


def flags(rep: dict) -> list[str]:
    """Plain-language red flags derived from the numbers."""
    h, a = rep["headline"], rep["analysis"]
    out = []
    tc = a.get("transcript") or {}
    if h.get("transcript_coverage") is not None and h["transcript_coverage"] < 0.8:
        extra = ""
        if tc.get("first_word_s") is not None:
            extra = f" (words only between {mmss(tc['first_word_s'])} and {mmss(tc['last_word_s'])})"
        out.append(f"**Transcript covers {tc.get('covered', '?')}/{tc.get('minutes', '?')} film minutes**{extra} "
                   f"— most moments were found without dialogue, so 'one-liner'/'funny' asks are near-blind.")
    if h.get("analysed_to") is not None and h["analysed_to"] < 0.95:
        out.append(f"Analysis stops at {mmss(a.get('last_moment_end_s'))} — the last "
                   f"{(1 - h['analysed_to']) * 100:.0f}% of the film has no moments.")
    failed = rep["summary_extra"].get("queries_failed")
    if failed:
        out.insert(0, f"**Incomplete run:** {failed:g} query(ies) did not run "
                      f"({rep['meta'].get('stop_reason') or 'see per-query errors'}); they are excluded from "
                      f"hit@k / MRR / tag precision, so this report is not comparable to a full run.")
    gaps = a.get("gaps_over_5min") or []
    if gaps:
        tot = sum(e - s for s, e in gaps)
        out.append(f"{len(gaps)} stretch(es) of 5+ minutes with no detected moment ({tot / 60:.0f} min total): "
                   + ", ".join(f"{mmss(s)}–{mmss(e)}" for s, e in gaps) + ".")
    ch = a.get("chunks") or {}
    if ch.get("failed"):
        out.append(f"{len(ch['failed'])}/{ch.get('planned', '?')} analysis chunks failed: {ch['failed']}.")
    if h.get("credits_violations"):
        out.append(f"{h['credits_violations']:g} clip/moment(s) start inside the end credits.")
    stale = sum(q["n_stale_returned"] for r in rep["runs"] for q in r["per_query"])
    if stale:
        out.append(f"Chat responses re-sent {stale} previously produced clip(s) alongside the new one(s) — "
                   f"the UI shows the user clips they did not ask for.")
    if rep["summary_extra"].get("letterbox_mean") and rep["summary_extra"]["letterbox_mean"] > 0.1:
        out.append(f"Delivered clips are on average {rep['summary_extra']['letterbox_mean'] * 100:.0f}% black bars "
                   f"(cropdetect) — the film's letterbox survives reframing, so vertical clips waste "
                   f"that share of the frame on black.")
    if h.get("captions_visible") == 0:
        out.append("No delivered clip has visible burned-in captions (bottom-third diff vs the pre-caption render).")
    if rep["summary_extra"].get("queries_empty"):
        out.append(f"{rep['summary_extra']['queries_empty']:g} query(ies) produced no new clip.")
    unreq = rep.get("unrequested_clips") or []
    if unreq:
        out.append(f"{len(unreq)} clip(s) were rendered during analysis that nobody asked for "
                   f"(not returned to the user; wasted render time).")
    return out


def render_md(rep: dict) -> str:
    gt, h, a = rep["gt"], rep["headline"], rep["analysis"]
    L: list[str] = []
    w = L.append
    w(f"# AutoClip eval · {gt['title']}")
    w("")
    w(f"> {gt['license_note']}. Ground truth: {gt['n_moments']} human-labelled moments, "
      f"{gt['n_queries']} ranked queries, film proper ends at {mmss(gt['film_end'])} "
      f"(duration {mmss(gt['duration'])}).")
    w("")
    meta = rep["meta"]
    w(f"`{meta['generated_utc']}` · mode **{meta['mode']}** · video `{meta.get('video_id')}` · "
      f"runs **{meta['runs']}** · git `{meta.get('git') or '?'}`")
    w("")
    w("## Scoreboard")
    w("")
    w("| Metric | Value | |")
    w("|---|---:|---|")
    for key, label, direction, kind in HEADLINE:
        v = h.get(key)
        std = h.get(key + "_std")
        val = fmt(v, kind) + (f" ± {std:.2f}" if std else "")
        vis = f"`{bar(v)}`" if kind == "rate" and v is not None else ""
        w(f"| {label} | **{val}** | {vis} |")
    w("")
    fl = flags(rep)
    if fl:
        w("**Red flags**")
        w("")
        for f in fl:
            w(f"- {f}")
        w("")

    # ---- per query
    w("## Per query")
    w("")
    w("| Query | Asked | Clips | hit@1 | hit@3 | MRR | Best truth rank | Tag prec. | Len ±10% | Aspect | Time | Cost |")
    w("|---|---|---:|:-:|:-:|---:|:-:|---:|:-:|:-:|---:|---:|")
    for r in rep["runs"]:
        for q in r["per_query"]:
            qd = rep["gt_queries"].get(q["query_id"], {})
            asked = " · ".join(x for x in [
                f"×{qd.get('count', 1)}" if qd.get("count", 1) > 1 else "",
                f"{qd['length']}s" if qd.get("length") else "",
                qd.get("frame") or ""] if x) or "–"
            name = (f"r{r['run']} " if len(rep["runs"]) > 1 else "") + f"**{q['query_id']}** — {_esc(q['prompt'])}"
            clips = f"{q['n_clips']}" + (f" (+{q['n_stale_returned']} stale)" if q["n_stale_returned"] else "")
            if q["error"]:
                clips = f"error: {_esc(q['error'])[:60]}"
            w(f"| {name} | {asked} | {clips} | {yn(q['hit_at_1'] and q['hit_at_1'] > 0) if q['hit_at_1'] is not None else '–'} "
              f"| {yn(q['hit_at_3'] and q['hit_at_3'] > 0) if q['hit_at_3'] is not None else '–'} | {fmt(q['mrr'])} "
              f"| {q['best_truth_rank'] or '–'} | {fmt(q['tag_precision'])} | {fmt(q['length_adherence_10'])} "
              f"| {fmt(q['aspect_adherence'])} | {fmt(q['elapsed_s'], 'secs')} | {fmt(q['cost_usd'], 'usd')} |")
    w("")
    w("<details><summary>Human truth per query</summary>")
    w("")
    mom = rep["gt_moments"]
    for qid, qd in rep["gt_queries"].items():
        tr = ", ".join(f"{i + 1}. `{t}` {mmss(mom[t]['start'])}–{mmss(mom[t]['end'])} {_esc(mom[t]['note'])}"
                       for i, t in enumerate(qd["truth"]))
        w(f"- **{qid}** ({', '.join(qd['tags'])}): {tr}")
    w("")
    w("</details>")
    w("")

    # ---- per clip
    w("## Per clip")
    w("")
    w("| # | Clip | Query | Title (app) | Span | Len asked→got | Frame asked→got | Human moment | Cat. | Capt. | Black bars |")
    w("|---:|---|---|---|---|---|---|---|:-:|:-:|---:|")
    n = 0
    for r in rep["runs"]:
        for c in r["per_clip"]:
            n += 1
            hm = (f"`{c['human_moment']}` {_esc(c['human_note'])} *({', '.join(c['human_tags'])})*"
                  if c["human_moment"] else "— none")
            ln = f"{c['asked_len'] or '–'}→{c['delivered_len']:.1f}s {yn(c['len_ok_10'])}" if c["delivered_len"] else "–"
            fr = f"{c['asked_frame'] or '–'}→{c['delivered_res'] or '?'} {yn(c['aspect_ok'])}"
            bb = f"{c['black_bar_frac'] * 100:.0f}%" if c["black_bar_frac"] is not None else "–"
            w(f"| {n} | `{c['clip_id']}` | {c['query_id']} | {_esc(c['title'])} | {mmss(c['start'])}–{mmss(c['end'])}"
              f"{' **CREDITS**' if c['credits'] else ''} | {ln} | {fr} | {hm} | {yn(c['tag_hit'])} "
              f"| {yn(c['captions_visible'])} | {bb} |")
    unreq = rep.get("unrequested_clips") or []
    if unreq:
        w("")
        w("Not requested (rendered during analysis, never returned): "
          + ", ".join(f"`{u['clip_id']}` {mmss(u['start'])}–{mmss(u['end'])}"
                      + (f" ≈ `{u['human_moment']}`" if u.get("human_moment") else "") for u in unreq))
    w("")

    # ---- moments / coverage
    w("## Moment detection")
    w("")
    if a.get("n_moments"):
        w(f"{a['n_moments']} fused moments in the DB, ranked by convergence score.")
        w("")
        w("| k | recall@k | precision@k |")
        w("|---|---:|---:|")
        for k in ("10", "25", "all"):
            w(f"| {k} | {fmt(a.get('moment_recall_' + k))} `{bar(a.get('moment_recall_' + k))}` "
              f"| {fmt(a.get('moment_precision_' + k))} |")
        w("")
        w("**Recall by tenth of the film** (human moments bucketed by midpoint; right column = system moments in that tenth)")
        w("")
        w("```")
        w("tenth  span            human  found  recall              system")
        mx = max([b["n_pred"] for b in a["coverage_by_tenth"]] + [1])
        for b in a["coverage_by_tenth"]:
            rec = b["recall"]
            w(f"{b['bin'] + 1:>4}   {mmss(b['lo']):>7}–{mmss(b['hi']):<7} {b['n_gt']:>5}  {b['n_hit']:>5}  "
              f"{bar(rec)} {fmt(rec):>4}   {bar(b['n_pred'] / mx, 12)} {b['n_pred']}")
        w("```")
        w("")
        if a.get("within_chunk"):
            wc = a["within_chunk"]
            w(f"**Where in each {int(rep['gt']['chunk_s'])}s analysis chunk moments are found** "
              f"({wc['n']} moments; source: {wc['source']}). Flat is healthy; a cliff after ~60s means the "
              f"tail of each chunk is not being looked at.")
            w("")
            w("```")
            mxc = max(wc["counts"] + [1])
            for i, cnt in enumerate(wc["counts"]):
                w(f"{int(wc['edges'][i]):>4}–{int(wc['edges'][i + 1]):<4}s  {bar(cnt / mxc, 24)} {cnt}")
            w("```")
            w("")
        if a.get("missed_moments"):
            w("<details><summary>Human moments with no matching system moment "
              f"({len(a['missed_moments'])})</summary>")
            w("")
            for mid in a["missed_moments"]:
                m = mom[mid]
                w(f"- `{mid}` {mmss(m['start'])}–{mmss(m['end'])} *{', '.join(m['tags'])}* — {_esc(m['note'])}")
            w("")
            w("</details>")
            w("")
    else:
        w("_No moments available for this run._")
        w("")
    t = a.get("transcript")
    if t:
        w(f"**Transcript:** {t['covered']}/{t['minutes']} film minutes contain at least one word"
          + (f" ({t['n_words']} words, first at {mmss(t['first_word_s'])}, last at {mmss(t['last_word_s'])})"
             if t.get("n_words") is not None else "") + (f" — {t['note']}" if t.get("note") else "") + ".")
        w("")

    # ---- diff
    if rep.get("diff"):
        d = rep["diff"]
        w("## Diff vs baseline")
        w("")
        w(f"Baseline: `{d['baseline_path']}` ({d['baseline_generated']}). Regression threshold: "
          f"{d['threshold']:.2f} absolute on rates; any increase on counts.")
        w("")
        w("| Metric | Baseline | Now | Δ | |")
        w("|---|---:|---:|---:|---|")
        kinds = {k: kind for k, _, _, kind in HEADLINE}
        for r in d["rows"]:
            kind = kinds[r["key"]]
            delta = "–" if r["delta"] is None else (("+" if r["delta"] >= 0 else "") + fmt(r["delta"], kind))
            v = {"better": "▲ better", "REGRESSION": "▼ **REGRESSION**", "same": "= same"}.get(r["verdict"], r["verdict"])
            w(f"| {r['label']} | {fmt(r['base'], kind)} | {fmt(r['now'], kind)} | {delta} | {v} |")
        w("")
        w(f"**{'REGRESSED' if d['regressed'] else 'No regression'}.**")
        w("")

    w("## How these numbers are computed")
    w("")
    w("- **Match rule:** a clip/moment matches a human moment iff they overlap by ≥ 50% of the *shorter* of the two.")
    w("- **hit@k / MRR:** the query's delivered clips, in delivery order, against the human's top-3 truth for that "
      "query (relevant = matches any of the three). *Best truth rank* = the best of the human's ranks that any clip hit.")
    w("- **Tag precision:** share of delivered clips that match *any* human moment carrying one of the asked tags "
      "(e.g. any `funny` moment, not just the top 3). **Clip precision:** share matching any human moment at all.")
    w("- **Moment recall/precision@k:** DB moments ranked by convergence score, one-to-one greedy matching by tIoU.")
    w("- **Length adherence:** |delivered − asked| ≤ 10% (and ≤ 25%) of asked, from ffprobe; queries that "
      "didn't specify a length/frame are excluded from that column.")
    w("- **Captions:** mean |final − reframed| pixel difference in the bottom third at 4 timestamps (≥ 2/255 = visible). "
      "**Black bars:** ffmpeg `cropdetect` on 3 windows.")
    w("- **Cost:** OpenRouter `/credits` usage delta (lags a few seconds; per-query values are indicative, totals reliable).")
    w("")
    return "\n".join(L)


CSV_COLS = ["run", "clip_id", "query_id", "rank", "title", "start", "end", "asked_len", "delivered_len",
            "len_ok_10", "len_ok_25", "asked_frame", "delivered_res", "aspect_ok", "human_moment", "human_tags",
            "tag_hit", "truth_hit", "credits", "has_audio", "black_bar_frac", "has_ass", "captions_visible", "probed"]


def render_csv(rep: dict) -> str:
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=CSV_COLS, extrasaction="ignore")
    wr.writeheader()
    for r in rep["runs"]:
        for c in r["per_clip"]:
            row = dict(c, run=r["run"], human_tags=";".join(c["human_tags"]))
            wr.writerow(row)
    return buf.getvalue()
