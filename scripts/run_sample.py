"""Run all five stages on a sample transcript with the real Claude API.

Auto-approves each stage (no human review) and prints a summary. Useful for
checking prompts end to end and for recording demo fixtures.

    python scripts/run_sample.py [--model claude-sonnet-5] [--transcript 01-kickoff.vtt]
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from core import config
from core.dor import pass_rate
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

    for stage in config.STAGES:
        run = pipeline.run_stage(meeting_id, stage)
        pipeline.approve(meeting_id, stage)
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
    print(f"Outputs saved to {out_dir}/")


if __name__ == "__main__":
    main()
