"""Run all five stages on a sample transcript with the real Claude API.

Auto-approves each stage (no human review) and prints a summary. Useful for
checking prompts end to end.

    python scripts/run_sample.py [--model claude-sonnet-5] [--transcript 01-kickoff.vtt] [--record]

--record saves the outputs as the demo-mode recording for that transcript
(samples/demo/<transcript>/), replacing any placeholder data, and also writes
the Excel export next to the JSON outputs.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from core import config
from core.demo import DEMO_DIR
from core.dor import pass_rate
from core.export import build_workbook, export_filename
from core.llm import ClaudeLLM, estimate_meeting_cost
from core.parsing import parse_transcript
from core.pipeline import Pipeline
from core.samples import SAMPLE_TRANSCRIPTS, load_sample_project, sample_transcript_path
from core.storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=config.DEFAULT_MODEL, choices=list(config.MODELS))
    parser.add_argument("--transcript", default="01-kickoff.vtt", choices=list(SAMPLE_TRANSCRIPTS))
    parser.add_argument("--out", default=str(config.DATA_DIR / "sample_run"))
    parser.add_argument("--record", action="store_true", help="Save as the demo-mode recording")
    args = parser.parse_args()
    load_dotenv()

    storage = Storage(":memory:")
    project_id = load_sample_project(storage)
    path = sample_transcript_path(args.transcript)
    transcript = parse_transcript(filename=path.name, data=path.read_bytes())
    title, date = SAMPLE_TRANSCRIPTS[args.transcript]
    meeting_id = storage.create_meeting(project_id, title, date, transcript.to_text(), transcript.source_format)

    print(f"Model: {args.model}  |  Estimated cost: ${estimate_meeting_cost(args.model, transcript.to_text()):.2f}")
    pipeline = Pipeline(storage, ClaudeLLM(args.model))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    outputs = {}
    for stage in config.STAGES:
        run = pipeline.run_stage(meeting_id, stage)
        pipeline.approve(meeting_id, stage)
        outputs[stage] = run["output"]
        (out_dir / f"{stage}.json").write_text(json.dumps(run["output"], indent=2))
        counts = {k: len(v) for k, v in run["output"].items() if isinstance(v, list)}
        print(f"{config.STAGE_LABELS[stage]:<32} ${run['cost_usd']:.3f}  {counts}")
        for w in pipeline.link_warnings(meeting_id, stage):
            print(f"    warning: {w}")

    unverified = pipeline.unverified_quotes(meeting_id)
    passed, total = pass_rate(pipeline.dor_results(meeting_id))
    print(f"\nUnverified quotes: {unverified or 'none'}")
    print(f"DoR pass rate: {passed}/{total}")
    print(f"Total cost: ${storage.meeting_cost(meeting_id):.2f}")
    xlsx = out_dir / export_filename(storage.get_meeting(meeting_id))
    xlsx.write_bytes(build_workbook(pipeline, meeting_id))
    print(f"Outputs and Excel export saved to {out_dir}/")

    if args.record:
        record_dir = DEMO_DIR / Path(args.transcript).stem
        record_dir.mkdir(parents=True, exist_ok=True)
        outputs["dor_review"] = outputs["stories"].pop("dor_review")
        for name, data in outputs.items():
            (record_dir / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        meta = {"placeholder": False, "transcript": args.transcript, "model": args.model,
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "cost_usd": round(storage.meeting_cost(meeting_id), 4)}
        (record_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        print(f"Demo recording saved to {record_dir}/")


if __name__ == "__main__":
    main()
