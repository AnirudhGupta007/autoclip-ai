"""Turn (ground truth, run record, probes) into a report dict. No I/O."""
from __future__ import annotations

import statistics
from typing import Optional

from . import metrics as M

# key, label, direction (+1 higher is better, -1 lower is better, 0 informational), kind
HEADLINE = [
    ("hit_at_3", "Query hit@3", +1, "rate"),
    ("hit_at_1", "Query hit@1", +1, "rate"),
    ("mrr", "Query MRR", +1, "rate"),
    ("tag_precision", "Tag precision (clip ⊂ asked category)", +1, "rate"),
    ("clip_precision", "Clip precision (clip ⊂ any human moment)", +1, "rate"),
    ("moment_recall_all", "Moment recall@all", +1, "rate"),
    ("moment_recall_25", "Moment recall@25", +1, "rate"),
    ("moment_precision_25", "Moment precision@25", +1, "rate"),
    ("length_adherence_10", "Length adherence (±10%)", +1, "rate"),
    ("length_adherence_25", "Length adherence (±25%)", +1, "rate"),
    ("aspect_adherence", "Aspect adherence", +1, "rate"),
    ("transcript_coverage", "Transcript coverage (film minutes)", +1, "rate"),
    ("analysed_to", "Analysed up to (fraction of film)", +1, "rate"),
    ("chunk_tail_share", "Moments in 2nd half of chunks (≈0.5 healthy)", 0, "rate"),
    ("captions_visible", "Clips with visible captions", +1, "rate"),
    ("duplicate_rate", "Duplicate clips", -1, "rate"),
    ("credits_violations", "Credits violations (clips+moments)", -1, "count"),
    ("cost_usd", "OpenRouter cost (USD)", 0, "usd"),
    ("wall_s", "Wall time, all queries (s)", 0, "secs"),
]


def _span(c: dict) -> M.Span:
    return (float(c["start"]), float(c["end"]))


def _res(s: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    if not s or "x" not in str(s):
        return None, None
    a, b = str(s).lower().split("x", 1)
    try:
        return int(a), int(b)
    except ValueError:
        return None, None


def clip_measurements(clip: dict, probe: Optional[dict]) -> dict:
    """Merge probe results with whatever the run recorded. Probe wins."""
    dur = (probe or {}).get("duration") or clip.get("delivered_len_s")
    if dur is None:
        dur = clip["end"] - clip["start"]
    w, h = (probe or {}).get("width"), (probe or {}).get("height")
    if not w:
        w, h = _res(clip.get("delivered_res"))
    return {"duration": dur, "width": w, "height": h,
            "has_audio": (probe or {}).get("has_audio"),
            "black_bar_frac": (probe or {}).get("black_bar_frac"),
            "has_ass": (probe or {}).get("has_ass"),
            "captions_visible": (probe or {}).get("captions_visible"),
            "probed": bool(probe and probe.get("exists"))}


def _best_moment(span: M.Span, moments: list[dict]) -> Optional[dict]:
    best, bt = None, 0.0
    for m in moments:
        g = (m["start"], m["end"])
        if M.matches(span, g):
            t = M.tiou(span, g)
            if t > bt:
                best, bt = m, t
    return best


def score_run(gt: dict, run: dict, run_queries: list[dict], probes: dict[str, dict]) -> dict:
    """Score one repetition (one pass over the queries)."""
    moments = gt["moments"]
    by_id = {m["id"]: m for m in moments}
    qdefs = {q["id"]: q for q in gt["queries"]}
    film_end = float(gt["film_end"])

    per_query, per_clip = [], []
    all_spans: list[M.Span] = []
    for qr in run_queries:
        q = qdefs.get(qr.get("query_id"))
        clips = [run["clips"][c] for c in qr.get("clip_ids", []) if c in run["clips"]]
        spans = [_span(c) for c in clips]
        all_spans.extend(spans)
        truth = [(by_id[t]["start"], by_id[t]["end"]) for t in (q["truth"] if q else [])]
        asked_len = q.get("length") if q else None
        asked_frame = q.get("frame") if q else None
        tag_flags = M.tag_hits(spans, moments, q["tags"]) if q else [False] * len(spans)
        rel = M.relevance(spans, truth)
        len10, len25, asp = [], [], []
        for i, c in enumerate(clips):
            meas = clip_measurements(c, probes.get(c["id"]))
            l10 = M.length_ok(meas["duration"], asked_len, 0.10)
            l25 = M.length_ok(meas["duration"], asked_len, 0.25)
            a = M.aspect_ok(meas["width"], meas["height"], asked_frame)
            len10.append(l10); len25.append(l25); asp.append(a)
            hm = _best_moment(spans[i], moments)
            per_clip.append({
                "clip_id": c["id"], "query_id": qr.get("query_id"), "rank": i + 1, "title": c.get("title"),
                "start": c["start"], "end": c["end"], "asked_len": asked_len, "delivered_len": meas["duration"],
                "asked_frame": asked_frame,
                "delivered_res": f"{meas['width']}x{meas['height']}" if meas["width"] else None,
                "len_ok_10": l10, "len_ok_25": l25, "aspect_ok": a,
                "human_moment": hm["id"] if hm else None, "human_note": hm["note"] if hm else None,
                "human_tags": hm["tags"] if hm else [], "tag_hit": tag_flags[i], "truth_hit": rel[i],
                "credits": c["start"] > film_end, "has_audio": meas["has_audio"],
                "black_bar_frac": meas["black_bar_frac"], "has_ass": meas["has_ass"],
                "captions_visible": meas["captions_visible"], "probed": meas["probed"],
            })
        n_returned = len(qr.get("returned_ids") or [])
        ran = q is not None and not qr.get("error")
        per_query.append({
            "query_id": qr.get("query_id"), "prompt": q["prompt"] if q else None, "message": qr.get("message"),
            "tags": q["tags"] if q else [], "truth": q["truth"] if q else [],
            "status": qr.get("status"), "error": qr.get("error"),
            "n_asked": q.get("count", 1) if q else None, "n_clips": len(clips),
            "n_returned": n_returned, "n_stale_returned": max(0, n_returned - len(clips)),
            "hit_at_1": M.hit_at_k(spans, truth, 1) if ran else None,
            "hit_at_3": M.hit_at_k(spans, truth, 3) if ran else None,
            "mrr": M.mrr(spans, truth) if ran else None,
            "best_truth_rank": M.best_truth_rank(spans, truth) if ran else None,
            "tag_precision": (sum(tag_flags) / len(tag_flags)) if tag_flags else (0.0 if ran else None),
            "clip_precision": (sum(1 for s in spans if _best_moment(s, moments)) / len(spans)) if spans else None,
            "length_adherence_10": M.rate(len10), "length_adherence_25": M.rate(len25),
            "aspect_adherence": M.rate(asp),
            "elapsed_s": qr.get("elapsed_s"), "cost_usd": qr.get("cost_usd"),
            "analysis_waited_s": qr.get("analysis_waited_s"),
            "agent_text": (qr.get("agent_text") or "")[:400],
        })

    # Queries that never ran (429, budget stop, transport error) are reported but
    # not scored — a quota failure must not read as "the model got it wrong".
    scored_q = [p for p in per_query if p["query_id"] and not p["error"]]
    tag_all = [c["tag_hit"] for c in per_clip]
    clip_any = [c["human_moment"] is not None for c in per_clip]
    s = {
        "n_queries": len(scored_q), "n_clips": len(per_clip),
        "hit_at_1": M.mean(p["hit_at_1"] for p in scored_q),
        "hit_at_3": M.mean(p["hit_at_3"] for p in scored_q),
        "mrr": M.mean(p["mrr"] for p in scored_q),
        # micro-averaged over clips: a query that returned nothing contributes 0 clips
        # here but 0 to hit@k, so both views are needed.
        "tag_precision": (sum(tag_all) / len(tag_all)) if tag_all else (0.0 if scored_q else None),
        "tag_precision_macro": M.mean(p["tag_precision"] for p in scored_q),
        "clip_precision": (sum(clip_any) / len(clip_any)) if clip_any else None,
        "length_adherence_10": M.rate(c["len_ok_10"] for c in per_clip),
        "length_adherence_25": M.rate(c["len_ok_25"] for c in per_clip),
        "aspect_adherence": M.rate(c["aspect_ok"] for c in per_clip),
        "duplicate_rate": M.duplicate_rate(all_spans),
        "captions_visible": M.rate(c["captions_visible"] for c in per_clip),
        "letterbox_mean": M.mean(c["black_bar_frac"] for c in per_clip),
        "has_audio": M.rate(c["has_audio"] for c in per_clip),
        "clip_credits_violations": len(M.credits_violations(all_spans, film_end)),
        "queries_empty": sum(1 for p in scored_q if p["n_clips"] == 0),
        "queries_failed": sum(1 for p in per_query if p["error"]),
        "queries_scored": len(scored_q),
        "wall_s": sum(p["elapsed_s"] or 0 for p in per_query),
        "cost_queries_usd": (sum(p["cost_usd"] for p in per_query if p["cost_usd"] is not None)
                             if any(p["cost_usd"] is not None for p in per_query) else None),
    }
    return {"summary": s, "per_query": per_query, "per_clip": per_clip}


def score_analysis(gt: dict, run: dict) -> dict:
    """Video-level analysis quality: moment retrieval, coverage, transcript."""
    film_end = float(gt["film_end"])
    gts = M.gt_spans(gt["moments"])
    moments = sorted(run.get("moments") or [], key=lambda m: -(m.get("convergence_score") or 0))
    mspans = [(float(m["start"]), float(m["end"])) for m in moments]
    out: dict = {"n_moments": len(mspans)}
    if mspans:
        for k, name in ((10, "10"), (25, "25"), (None, "all")):
            out[f"moment_recall_{name}"] = M.recall_at_k(mspans, gts, k)
            out[f"moment_precision_{name}"] = M.precision_at_k(mspans, gts, k)
        out["moment_duplicate_rate"] = M.duplicate_rate(sorted(mspans))
        out["coverage_by_tenth"] = M.coverage_by_tenth(mspans, gts, film_end)
        out["analysed_to"] = M.last_analysed_fraction(mspans, film_end)
        out["last_moment_end_s"] = max(e for _, e in mspans)
        out["gaps_over_5min"] = [list(g) for g in M.coverage_gaps(mspans, film_end, 300.0)]
        out["moment_credits_violations"] = len(M.credits_violations(mspans, film_end))
        matched = M.greedy_match(mspans, gts)
        out["moment_matches"] = [{"gt": gt["moments"][j]["id"], "start": mspans[i][0], "end": mspans[i][1],
                                  "rank": i + 1, "tiou": round(t, 3)} for i, j, t in matched]
        out["missed_moments"] = [m["id"] for j, m in enumerate(gt["moments"]) if j not in {jj for _, jj, _ in matched}]
    ch = gt.get("chunking", {})
    chunk_s, ov = float(ch.get("chunk_s", 120)), float(ch.get("overlap_s", 10))
    raw = run.get("raw_chunk_moments")
    if raw:
        offs = M.within_chunk_offsets([r["start"] for r in raw], chunk_s, ov, [r["chunk_index"] for r in raw])
        src = "raw per-chunk moments (SSE), exact chunk index"
    else:
        offs = M.within_chunk_offsets([s for s, _ in mspans], chunk_s, ov)
        src = "fused moments, chunk inferred as floor(start / stride)"
    if offs:
        out["within_chunk"] = {**M.within_chunk_histogram(offs, chunk_s, 20.0), "source": src}
        out["chunk_tail_share"] = out["within_chunk"]["frac_second_half"]
    if run.get("chunks"):
        out["chunks"] = run["chunks"]
    t = run.get("transcript") or {}
    if t.get("word_starts") is not None:
        tc = M.transcript_minute_coverage(t["word_starts"], film_end)
        out["transcript_coverage"] = tc["fraction"]
        out["transcript"] = {k: tc[k] for k in ("minutes", "covered")} | {
            "n_words": len(t["word_starts"]),
            "first_word_s": min(t["word_starts"]) if t["word_starts"] else None,
            "last_word_s": max(t["word_starts"]) if t["word_starts"] else None}
    elif t.get("span_only"):
        a, b = t["span_only"]
        tc = M.transcript_minute_coverage([x for x in range(int(a), int(b) + 1, 60)] + [b], film_end)
        out["transcript_coverage"] = tc["fraction"]
        out["transcript"] = {"minutes": tc["minutes"], "covered": tc["covered"],
                             "note": "upper bound from first/last word only"}
    return out


def aggregate(run_scores: list[dict]) -> dict:
    """Mean and stdev of each numeric summary key across repetitions."""
    keys = sorted({k for r in run_scores for k, v in r["summary"].items() if isinstance(v, (int, float))})
    agg = {}
    for k in keys:
        vals = [r["summary"][k] for r in run_scores if isinstance(r["summary"].get(k), (int, float))]
        if not vals:
            continue
        agg[k] = {"mean": statistics.fmean(vals), "std": statistics.pstdev(vals) if len(vals) > 1 else 0.0,
                  "n": len(vals)}
    return agg


def headline(run_scores: list[dict], analysis: dict, run: dict) -> dict:
    agg = aggregate(run_scores)
    h: dict = {}
    for key, _, _, _ in HEADLINE:
        if key in agg:
            h[key] = agg[key]["mean"]
            if agg[key]["n"] > 1:
                h[key + "_std"] = agg[key]["std"]
        elif key in analysis:
            h[key] = analysis[key]
    h["credits_violations"] = (agg.get("clip_credits_violations", {}).get("mean", 0) or 0) + \
        (analysis.get("moment_credits_violations") or 0)
    total = (run.get("cost") or {}).get("total_usd")
    h["cost_usd"] = total if total is not None else agg.get("cost_queries_usd", {}).get("mean")
    return h


def diff(head: dict, base_head: dict, threshold: float) -> tuple[list[dict], bool]:
    rows, regressed = [], False
    for key, label, direction, kind in HEADLINE:
        a, b = head.get(key), base_head.get(key)
        if a is None or b is None:
            rows.append({"key": key, "label": label, "now": a, "base": b, "delta": None, "verdict": "n/a"})
            continue
        d = a - b
        if direction == 0:
            verdict = "info"
        else:
            tol = threshold if kind == "rate" else 0.0
            if direction * d > tol:
                verdict = "better"
            elif direction * d < -tol:
                verdict = "REGRESSION"
                regressed = True
            else:
                verdict = "same"
        rows.append({"key": key, "label": label, "now": a, "base": b, "delta": d, "verdict": verdict})
    return rows, regressed
