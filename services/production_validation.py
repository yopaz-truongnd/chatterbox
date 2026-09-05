"""CLI Entrypoint for running Production Validation via python -m services.production_validation."""

from __future__ import annotations

import argparse
import sys
import yaml

from services.production_validation_models import ProductionValidationRequest
from services.production_validation_service import ProductionValidationService


def main(args_list: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m services.production_validation",
        description="Execute canonical real-runtime production validation",
    )
    parser.add_argument("--script", help="Path to input story script file")
    parser.add_argument("--provider", default="local", help="TTS Provider (local, gemini, fake)")
    parser.add_argument("--model", default="nano", help="TTS Model name")
    parser.add_argument("--language", default="en", help="Story language")
    parser.add_argument("--voice-mode", default="tts", help="Voice mode")
    parser.add_argument("--reference-voice", help="Path to narrator reference voice")
    parser.add_argument("--output-report", dest="output_report", help="Destination path for YAML report")
    parser.add_argument("--profile", help="Path or ID of validation profile YAML")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args(args_list if args_list is not None else sys.argv[1:])

    req = ProductionValidationRequest(
        validation_profile_id=args.profile,
        script_path=args.script,
        provider=args.provider,
        model=args.model,
        language=args.language,
        voice_mode=args.voice_mode,
        reference_voice=args.reference_voice,
        output_report_path=args.output_report,
        output_formats=["wav"],
    )

    service = ProductionValidationService(allow_raw_paths=True)
    print(f"Starting production validation with provider='{req.provider}', model='{req.model}'...")
    report = service.validate(req)

    if args.json:
        import json
        print(json.dumps(report.model_dump(mode="json"), indent=2))
    else:
        print("\n================ PRODUCTION VALIDATION REPORT ================")
        print(f"Validation ID:  {report.validation_id}")
        print(f"Status:         {report.status}")
        print(f"Verdict:        {report.verdict.value}")
        print(f"Total Duration: {report.total_duration_ms:.1f} ms")
        print(f"Beats:          {report.beat_count} (Passed: {report.qc_pass_count}, Review: {report.qc_review_count}, Failed: {report.qc_failed_count})")
        print(f"Artifacts:      {len(report.artifacts)} produced")
        if report.warnings:
            print("\nWarnings:")
            for w in report.warnings:
                print(f"  - {w}")
        if report.failures:
            print("\nFailures:")
            for f in report.failures:
                print(f"  - [{f.step_name}] {f.code}: {f.message}")
        print("=============================================================\n")

    return 0 if report.status == "completed" and report.verdict != "FAIL" else 1


if __name__ == "__main__":
    sys.exit(main())
