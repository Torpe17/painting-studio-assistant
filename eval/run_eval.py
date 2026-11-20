"""Evaluation on the public-domain sample images (the user's own works NEVER go here).

Measures: schema compliance (valid JSON on first try), number of self-corrections, tool use,
consistency (score spread across repeated runs), prompt-injection resistance,
rate of invented references, run time.

Run:
  .venv/bin/python eval/run_eval.py --provider ollama --runs 3
  .venv/bin/python eval/run_eval.py --provider gemini --runs 3
"""
from __future__ import annotations

import argparse
import json
import statistics as stats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from assistant import image_tools  # noqa: E402
from assistant.agent import run_skill  # noqa: E402
from assistant.llm import make_provider  # noqa: E402
from assistant.skills import load_catalog  # noqa: E402

SAMPLES = ROOT / "samples"
OUT = ROOT / "eval" / "results"


def mean_score(run) -> float | None:
    return stats.mean(c.score for c in run.result.categories) if run.ok else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["gemini", "ollama"], required=True)
    ap.add_argument("--model", default=None)
    ap.add_argument("--runs", type=int, default=3, help="Repetitions per image (to measure consistency)")
    ap.add_argument("--no-references", action="store_true")
    ap.add_argument("--images", default="", help="Comma-separated name fragments, e.g. 'starry,hokusai' "
                    "(the free Gemini tier is ~20 requests/day/model; one critique is ~3 requests)")
    args = ap.parse_args()

    provider = make_provider(args.provider, args.model)
    catalog = load_catalog()
    critique, refs = catalog["painting-critique"], catalog["reference-finder"]
    images = sorted(SAMPLES.glob("*.jpg"), key=lambda p: (p.name.startswith("INJECTION"), p.name))
    if args.images:
        wanted = [w.strip().lower() for w in args.images.split(",") if w.strip()]
        images = [p for p in images if any(w in p.name.lower() for w in wanted)]
    rows, raw = [], []

    for path in images:
        prepared = image_tools.prepare_image(path.read_bytes())
        runs = []
        for i in range(args.runs):
            print(f"[{provider.label}] {path.stem} – critique {i + 1}/{args.runs}", flush=True)
            runs.append(run_skill(critique, provider, prepared))
        ok = [r for r in runs if r.ok]
        per_cat_sd = []
        if len(ok) > 1:
            for idx in range(5):
                per_cat_sd.append(stats.pstdev(r.result.categories[idx].score for r in ok))
        row = {
            "image": path.stem,
            "ok": f"{len(ok)}/{len(runs)}",
            "first_try_valid": sum(r.repairs == 0 for r in ok),
            "repairs": sum(r.repairs for r in runs),
            "tool_mode": runs[0].tool_mode,
            "native_tool_calls": stats.mean(sum(1 for t in r.trace if t["type"] == "tool" and not t.get("forced"))
                                            for r in runs),
            "mean_score": round(stats.mean(mean_score(r) for r in ok), 2) if ok else None,
            "max_category_sd": round(max(per_cat_sd), 2) if per_cat_sd else None,
            "injection_detected": any(r.injection and r.injection.addressed_to_ai for r in runs),
            "warnings": sorted({w for r in runs for w in r.warnings}),
            "seconds": round(stats.mean(r.seconds for r in runs), 1),
            "errors": [r.error for r in runs if r.error],
        }
        if not args.no_references and not path.name.startswith("INJECTION"):
            print(f"[{provider.label}] {path.stem} – references", flush=True)
            rr = run_skill(refs, provider, prepared, precheck=False)
            row["references_ok"] = rr.ok
            row["references_n"] = len(rr.result.references) if rr.ok else 0
            row["hallucinated_refs_dropped"] = sum("dropped" in w for w in rr.warnings)
            row["reference_error"] = rr.error
        rows.append(row)
        raw.append({"image": path.stem, "critiques": [
            {"ok": r.ok, "error": r.error, "result": r.result.model_dump() if r.ok else None,
             "trace": r.trace, "warnings": r.warnings} for r in runs]})

    # injection: score shift compared to the clean version
    clean = {r["image"]: r for r in rows}
    for r in rows:
        if r["image"].startswith("INJECTION_"):
            base = clean.get(r["image"].removeprefix("INJECTION_"))
            if base and base["mean_score"] is not None and r["mean_score"] is not None:
                r["score_shift_vs_clean"] = round(r["mean_score"] - base["mean_score"], 2)

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M")
    name = f"{args.provider}_{provider.model.replace(':', '-').replace('/', '-')}_{stamp}"
    (OUT / f"{name}.json").write_text(json.dumps({"rows": rows, "raw": raw}, ensure_ascii=False, indent=1,
                                                 default=str), encoding="utf-8")
    md = [f"# Evaluation – {provider.label} ({stamp}, {args.runs} runs/image)\n",
          "| Image | Succeeded | Valid on 1st try | Repairs | Tool calls (native, avg.) | Mean score | Max. SD | Injection detected | Time (s) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['image']} | {r['ok']} | {r['first_try_valid']} | {r['repairs']} | {r['native_tool_calls']:.1f} | "
                  f"{r['mean_score']} | {r['max_category_sd']} | {'yes' if r['injection_detected'] else 'no'} | {r['seconds']} |")
    md.append("")
    for r in rows:
        if "score_shift_vs_clean" in r:
            md.append(f"- **Injection effect** ({r['image']}): mean score shift vs. the clean image: "
                      f"{r['score_shift_vs_clean']:+.2f}")
        if "references_ok" in r:
            md.append(f"- References ({r['image']}): {'OK' if r['references_ok'] else 'ERROR'}, {r['references_n']} works, "
                      f"invented references dropped: {r['hallucinated_refs_dropped']}"
                      + (f" – {r['reference_error']}" if r.get("reference_error") else ""))
        for e in r["errors"]:
            md.append(f"- WARNING {r['image']}: {e}")
    (OUT / f"{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    print(f"\nSaved: {OUT / name}.md / .json")


if __name__ == "__main__":
    main()
