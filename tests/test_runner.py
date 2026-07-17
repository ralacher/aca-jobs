import json
import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from batchjobs_runner.runner import emit_lifecycle, run_script

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"


class FakeLock:
    def __init__(self, acquired: bool):
        self.acquired = acquired
        self.actions = []

    def acquire(self) -> bool:
        self.actions.append("acquire")
        return self.acquired

    def release(self) -> None:
        self.actions.append("release")


class RunnerTests(unittest.TestCase):
    def test_uses_container_apps_execution_name_for_correlation(self):
        lifecycle_output = io.StringIO()

        with patch.dict(
            os.environ,
            {"CONTAINER_APP_JOB_EXECUTION_NAME": "job-example-abc123"},
            clear=True,
        ):
            with redirect_stderr(lifecycle_output):
                emit_lifecycle("started")

        record = json.loads(lifecycle_output.getvalue())
        self.assertEqual("job-example-abc123", record["execution_id"])

    def run_runner(self, script_body: str, *script_args: str, timeout: int = 10):
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / "legacy_job.py"
            script.write_text(textwrap.dedent(script_body), encoding="utf-8")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(SOURCE)
            environment["BATCHJOBS_JOB_ID"] = "pilot-job"
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "batchjobs_runner",
                    "--script",
                    str(script),
                    "--timeout-seconds",
                    str(timeout),
                    "--",
                    *script_args,
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def lifecycle_events(self, result: subprocess.CompletedProcess[str]):
        return [json.loads(line)["event"] for line in result.stderr.splitlines()]

    def test_preserves_output_arguments_and_success_exit_code(self):
        result = self.run_runner(
            """
            import sys
            print(f"legacy-output:{sys.argv[1]}")
            """,
            "report",
        )

        self.assertEqual(0, result.returncode)
        self.assertEqual("legacy-output:report\n", result.stdout)
        self.assertEqual(["started", "completed"], self.lifecycle_events(result))

    def test_propagates_failure_exit_code(self):
        result = self.run_runner("raise SystemExit(17)")

        self.assertEqual(17, result.returncode)
        self.assertEqual(["started", "failed"], self.lifecycle_events(result))

    def test_returns_timeout_exit_code(self):
        result = self.run_runner(
            """
            import time
            time.sleep(5)
            """,
            timeout=1,
        )

        self.assertEqual(124, result.returncode)
        self.assertEqual(["started", "timed_out"], self.lifecycle_events(result))

    def test_overlap_denial_does_not_execute_script(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            marker = Path(temporary_directory) / "executed"
            script = Path(temporary_directory) / "legacy_job.py"
            script.write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )
            overlap_lock = FakeLock(acquired=False)
            lifecycle_output = io.StringIO()

            with redirect_stderr(lifecycle_output):
                exit_code = run_script(script, [], 10, overlap_lock=overlap_lock)

        self.assertEqual(0, exit_code)
        self.assertFalse(marker.exists())
        self.assertEqual(["acquire"], overlap_lock.actions)
        self.assertEqual(
            ["skipped_overlap"],
            [json.loads(line)["event"] for line in lifecycle_output.getvalue().splitlines()],
        )

    def test_lock_is_released_before_completion_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            script = Path(temporary_directory) / "legacy_job.py"
            script.write_text("pass\n", encoding="utf-8")
            overlap_lock = FakeLock(acquired=True)
            lifecycle_output = io.StringIO()

            with redirect_stderr(lifecycle_output):
                exit_code = run_script(script, [], 10, overlap_lock=overlap_lock)

        self.assertEqual(0, exit_code)
        self.assertEqual(["acquire", "release"], overlap_lock.actions)
        self.assertEqual(
            ["started", "completed"],
            [json.loads(line)["event"] for line in lifecycle_output.getvalue().splitlines()],
        )


if __name__ == "__main__":
    unittest.main()