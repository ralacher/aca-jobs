from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Sequence

from croniter import croniter

RESERVED_ENVIRONMENT_VARIABLES = {
    "AZURE_CLIENT_ID",
    "BATCHJOBS_IMAGE_REVISION",
    "BATCHJOBS_JOB_ID",
    "BATCHJOBS_LOCK_CONTAINER_URL",
    "BATCHJOBS_TRIGGER",
}


def compile_manifest(manifest: dict[str, object], manifest_path: Path) -> dict[str, object]:
    job_id = str(manifest["id"])
    if manifest_path.parent.name != job_id:
        raise ValueError(
            f"Manifest id {job_id!r} must match directory {manifest_path.parent.name!r}"
        )

    secret_references = manifest.get("secretReferences", [])
    volume_mounts = manifest.get("volumeMounts", [])
    if secret_references:
        raise ValueError(f"{job_id}: secretReferences deployment is not implemented")
    if volume_mounts:
        raise ValueError(f"{job_id}: volumeMounts deployment is not implemented")

    environment = dict(manifest.get("environment", {}))
    reserved = sorted(RESERVED_ENVIRONMENT_VARIABLES.intersection(environment))
    if reserved:
        raise ValueError(f"{job_id}: reserved environment variables: {', '.join(reserved)}")

    runtime = dict(manifest["runtime"])
    schedule = dict(manifest["schedule"])
    monitoring = dict(manifest.get("monitoring", {}))
    cron_expression = str(schedule["cronExpressionUtc"])
    portable_cron = re.fullmatch(r"[0-9*/,\-]+(?: [0-9*/,\-]+){4}", cron_expression)
    if portable_cron is None or not croniter.is_valid(cron_expression):
        raise ValueError(f"{job_id}: invalid five-field UTC cron expression")

    script_path = manifest_path.parent / str(runtime["script"])
    if not script_path.is_file():
        raise ValueError(f"{job_id}: script does not exist: {script_path}")

    return {
        "arguments": list(runtime.get("arguments", [])),
        "cpu": runtime["cpu"],
        "cronExpressionUtc": cron_expression,
        "enabled": manifest["enabled"],
        "environment": [
            {"name": name, "value": environment[name]} for name in sorted(environment)
        ],
        "id": job_id,
        "memory": runtime["memory"],
        "monitoring": {
            "alertOnFailure": monitoring.get("alertOnFailure", True),
            "alertOnOverlap": monitoring.get("alertOnOverlap", False),
            "alertOnStale": monitoring.get("alertOnStale", False),
            "maxSilenceMinutes": monitoring.get("maxSilenceMinutes", 1440),
        },
        "retryLimit": dict(manifest["execution"])["retryLimit"],
        "script": f"/app/jobs/{job_id}/{runtime['script']}",
        "timeoutSeconds": runtime["timeoutSeconds"],
    }


def compile_directory(jobs_directory: Path) -> dict[str, object]:
    manifest_paths = sorted(jobs_directory.glob("*/job.json"))
    if not manifest_paths:
        raise ValueError(f"No job manifests found under {jobs_directory}")

    definitions = []
    seen_ids: set[str] = set()
    for manifest_path in manifest_paths:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        definition = compile_manifest(manifest, manifest_path)
        job_id = str(definition["id"])
        if job_id in seen_ids:
            raise ValueError(f"Duplicate job id: {job_id}")
        seen_ids.add(job_id)
        definitions.append(definition)

    return {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {"jobDefinitions": {"value": definitions}},
    }


def serialize(document: dict[str, object]) -> str:
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile job manifests into deterministic Bicep parameters."
    )
    parser.add_argument("--jobs-directory", type=Path, default=Path("jobs"))
    parser.add_argument("--output", type=Path, default=Path(".cache/jobs.parameters.json"))
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the output file does not match the compiled manifests.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rendered = serialize(compile_directory(args.jobs_directory))
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                f"{args.output} is stale; run python tools/batchjobs_compile.py"
            )
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())