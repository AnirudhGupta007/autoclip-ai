"""Optional RAGAS judge for an eval run (`eval_movie.py --ragas`).

The ID-based metrics (hit@k, tag precision, recall) stay primary — they are
exact for clip ranking. RAGAS adds two things they can't see:

  * faithfulness      — per clip: does its title claim anything that is not
                        in the clip's own transcript? (hallucinated titles).
                        Averaged per query. The agent's chat reply is not
                        judged: it states lengths/scores/aspect, which no
                        transcript can support (scored 0.00 across the board
                        on a first try).
  * context precision — per query: are the returned clips, in rank order,
                        relevant to the request? Judged against the human
                        notes of the query's truth moments (the reference).

The judge is a cheap OpenRouter model through ragas' LangChain wrapper.
`ragas` is a dev-only dependency (pyproject `[project.optional-dependencies]
eval`), imported lazily: without it the step is skipped, not failed.
Transcript text is only held in memory — the report stores scores only
(the Wild Target dialogue must never be written to disk/git).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

JUDGE_MODEL = "google/gemini-2.5-flash-lite"
PRICE_PER_M = {"google/gemini-2.5-flash-lite": (0.10, 0.40)}   # USD per 1M tokens in/out
PROMPT_OVERHEAD_TOKENS = 1500   # ragas' few-shot instruction prompt, per LLM call
MAX_CONTEXT_CHARS = 2000
CLIP_QUESTION = "What is said or happens in this clip?"


def _clip_text(c: dict) -> str:
    return " ".join((c.get("transcript") or "").split())[:MAX_CONTEXT_CHARS]


def build_samples(per_query: list[dict], clips_by_id: dict[str, dict],
                  gt_moments: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """(faithfulness samples: one per titled clip with a transcript;
    context-precision samples: one per query with a human reference). Each
    sample carries its `query_id` (stripped before it reaches ragas)."""
    faith, ctxp = [], []
    for q in per_query:
        clips = [clips_by_id[i] for i in q.get("returned_ids") or q.get("clip_ids") or [] if i in clips_by_id]
        ctx = [t for t in (_clip_text(c) for c in clips) if t]
        if not ctx:
            continue
        for c in clips:
            text = _clip_text(c)
            if text and (c.get("title") or "").strip():
                # The bare title as the answer: "Clip title: X" became the claim
                # "the clip's title is X", which no transcript supports (0.06).
                faith.append({"query_id": q["query_id"], "user_input": CLIP_QUESTION,
                              "response": c["title"].strip(), "retrieved_contexts": [text]})
        notes = [gt_moments[t]["note"] for t in q.get("truth") or [] if t in gt_moments]
        if notes:
            ctxp.append({"query_id": q["query_id"], "user_input": q.get("message") or "",
                         "reference": "Good answers: " + " | ".join(notes),
                         "retrieved_contexts": ctx})
    return faith, ctxp


def estimate_usd(faith: list[dict], ctxp: list[dict], model: str = JUDGE_MODEL) -> float:
    """Upper-bound-ish cost estimate (chars/4 tokens). Faithfulness ~= 2 calls
    per sample (statement split + NLI over all contexts); context precision
    = 1 call per retrieved context."""
    p_in, p_out = (0.0, 0.0) if model.endswith(":free") else \
        PRICE_PER_M.get(model, (1.0, 4.0))   # unknown model: assume pricey
    tin = tout = 0
    for s in faith:
        body = (len(s["response"]) + sum(map(len, s["retrieved_contexts"]))) // 4
        tin += 2 * (PROMPT_OVERHEAD_TOKENS + body)
        tout += 2 * 400
    for s in ctxp:
        for c in s["retrieved_contexts"]:
            tin += PROMPT_OVERHEAD_TOKENS + (len(s["user_input"]) + len(s["reference"]) + len(c)) // 4
            tout += 200
    return (tin * p_in + tout * p_out) / 1e6


def _mean(xs) -> Optional[float]:
    xs = [x for x in xs if x is not None and x == x]   # drop None/NaN
    return sum(xs) / len(xs) if xs else None


def run(per_query: list[dict], clips_by_id: dict[str, dict], gt_moments: dict[str, dict], *,
        api_key: Optional[str], base_url: str, budget_usd: float, model: str = JUDGE_MODEL,
        usage: Optional[Callable[[], Optional[float]]] = None,
        log: Callable[[str], None] = print) -> dict:
    """Score a run. Returns {"skipped": reason} or the scores + spend."""
    faith, ctxp = build_samples(per_query, clips_by_id, gt_moments)
    if not faith:
        return {"skipped": "no returned clips with titles + transcripts"}
    est = estimate_usd(faith, ctxp, model)
    if est > budget_usd:
        return {"skipped": f"estimated ${est:.3f} > remaining budget ${budget_usd:.3f}", "estimate_usd": est}
    if not api_key:
        return {"skipped": "no OPENROUTER_API_KEY"}
    try:
        from langchain_openai import ChatOpenAI
        from ragas import EvaluationDataset, RunConfig, evaluate
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference
    except ImportError as e:
        return {"skipped": f"ragas not installed ({e}); pip install -e 'backend[eval]'"}

    llm = LangchainLLMWrapper(ChatOpenAI(model=model, api_key=api_key, base_url=base_url,
                                         temperature=0.0, max_tokens=4096, timeout=120))
    before = usage() if usage else None
    t0 = time.time()
    strip = lambda rows: [{k: v for k, v in r.items() if k != "query_id"} for r in rows]  # noqa: E731
    log(f"ragas: {len(faith)} faithfulness + {len(ctxp)} context-precision samples "
        f"with {model} (est. ${est:.3f})")
    rc = RunConfig(max_workers=4, timeout=180, max_retries=3)   # small pool: free/cheap judges rate-limit
    f_res = evaluate(EvaluationDataset.from_list(strip(faith)), metrics=[Faithfulness(llm=llm)],
                     run_config=rc, show_progress=False).to_pandas()
    f_scores = [None if v != v else float(v) for v in f_res["faithfulness"]]
    c_scores: list[Optional[float]] = []
    if ctxp:
        c_res = evaluate(EvaluationDataset.from_list(strip(ctxp)),
                         metrics=[LLMContextPrecisionWithReference(llm=llm)], run_config=rc,
                         show_progress=False).to_pandas()
        col = [c for c in c_res.columns if c.startswith("llm_context_precision")][0]
        c_scores = [None if v != v else float(v) for v in c_res[col]]
    after = usage() if usage else None
    spent = (after - before) if (before is not None and after is not None) else None
    return {
        "judge_model": model,
        "faithfulness": _mean(f_scores),
        "context_precision": _mean(c_scores),
        "per_query": _merge(faith, f_scores, ctxp, c_scores),
        "n_faithfulness": len(faith), "n_context_precision": len(ctxp),
        "estimate_usd": est, "cost_usd": spent, "wall_s": round(time.time() - t0, 1),
    }


def _merge(faith, f_scores, ctxp, c_scores) -> dict:
    out: dict[str, dict] = {}
    by_q: dict[str, list] = {}
    for s, f in zip(faith, f_scores):
        by_q.setdefault(s["query_id"], []).append(f)
    for qid, fs in by_q.items():
        out.setdefault(qid, {})["faithfulness"] = _mean(fs)
    for s, c in zip(ctxp, c_scores):
        out.setdefault(s["query_id"], {})["context_precision"] = c
    return out
