from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence

from .overlap import OverlapLock, lock_from_environment

TIMEOUT_EXIT_CODE = 124
PLATFORM_ERROR_EXIT_CODE = 70


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def emit_lifecycle(event: str, **details: object) -> None:
    record = {
        "schema": "batchjobs.lifecycle.v1",
        "event": event,
        "timestamp": utc_timestamp(),
        "job_id": os.environ.get("BATCHJOBS_JOB_ID", "unknown"),
        "execution_id": os.environ.get(
            "BATCHJOBS_EXECUTION_ID",
            os.environ.get("CONTAINER_APP_JOB_EXECUTION_NAME", "unknown"),
        ),
        "trigger": os.environ.get("BATCHJOBS_TRIGGER", "unknown"),
        "image_revision": os.environ.get("BATCHJOBS_IMAGE_REVISION", "unknown"),
        **details,
    }
    print(json.dumps(record, separators=(",", ":")), file=sys.stderr, flush=True)


def run_script(
    script: Path,
    script_args: Sequence[str],
    timeout_seconds: int,
    overlap_lock: OverlapLock | None = None,
) -> int:
    resolved_script = script.resolve()
    if not resolved_script.is_file():
        emit_lifecycle("rejected", script=str(resolved_script), reason="script_not_found")
        return 2

    overlap_lock = overlap_lock or lock_from_environment()
    try:
        acquired = overlap_lock.acquire()
    except Exception as error:
        emit_lifecycle(
            "lock_failed",
            script=str(resolved_script),
            error_type=type(error).__name__,
        )
        return PLATFORM_ERROR_EXIT_CODE

    if not acquired:
        emit_lifecycle("skipped_overlap", script=str(resolved_script))
        return 0

    command = [sys.executable, str(resolved_script), *script_args]
    started_at = time.monotonic()
    emit_lifecycle("started", script=str(resolved_script), timeout_seconds=timeout_seconds)

    try:
        try:
            result = subprocess.run(command, check=False, timeout=timeout_seconds)
            exit_code = result.returncode
            event = "completed" if exit_code == 0 else "failed"
        except subprocess.TimeoutExpired:
            exit_code = TIMEOUT_EXIT_CODE
            event = "timed_out"
    finally:
        try:
            overlap_lock.release()
        except Exception as error:
            emit_lifecycle(
                "lock_failed",
                script=str(resolved_script),
                operation="release",
                error_type=type(error).__name__,
            )
            return PLATFORM_ERROR_EXIT_CODE

    duration_ms = round((time.monotonic() - started_at) * 1000)
    event_details = {
        "script": str(resolved_script),
        "duration_ms": duration_ms,
        "exit_code": exit_code,
    }
    if event == "timed_out":
        event_details["timeout_seconds"] = timeout_seconds
    emit_lifecycle(
        event,
        **event_details,
    )
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an unchanged Python job with lifecycle telemetry."
    )
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("script_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be greater than zero")

    script_args = args.script_args
    if script_args[:1] == ["--"]:
        script_args = script_args[1:]
    return run_script(args.script, script_args, args.timeout_seconds)
