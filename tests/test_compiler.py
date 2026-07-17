import json
import tempfile
import unittest
from pathlib import Path

from batchjobs_deploy.compiler import compile_directory, compile_manifest, serialize

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_MANIFEST_PATH = ROOT / "jobs" / "example-report" / "job.json"


class CompilerTests(unittest.TestCase):
    def test_compiles_manifest_to_container_job_parameters(self):
        document = compile_directory(ROOT / "jobs")

        definitions = document["parameters"]["jobDefinitions"]["value"]
        self.assertEqual(len(definitions), 1)
        self.assertEqual(
            definitions[0],
            {
                "arguments": [],
                "cpu": 0.5,
                "cronExpressionUtc": "30 10 * * 1-5",
                "enabled": True,
                "environment": [
                    {"name": "EXAMPLE_MODE", "value": "validation-only"}
                ],
                "id": "example-report",
                "memory": "1Gi",
                "monitoring": {
                    "alertOnFailure": True,
                    "alertOnOverlap": False,
                    "alertOnStale": False,
                    "maxSilenceMinutes": 1440,
                },
                "retryLimit": 0,
                "script": "/app/jobs/example-report/script.py",
                "timeoutSeconds": 900,
            },
        )

    def test_output_is_deterministic(self):
        first = serialize(compile_directory(ROOT / "jobs"))
        second = serialize(compile_directory(ROOT / "jobs"))

        self.assertEqual(first, second)

    def test_rejects_reserved_environment_variables(self):
        manifest = json.loads(EXAMPLE_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["environment"]["BATCHJOBS_JOB_ID"] = "override"

        with self.assertRaisesRegex(ValueError, "reserved environment variables"):
            compile_manifest(manifest, EXAMPLE_MANIFEST_PATH)

    def test_rejects_invalid_or_non_five_field_cron(self):
        manifest = json.loads(EXAMPLE_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["schedule"]["cronExpressionUtc"] = "0 30 10 * * 1-5"

        with self.assertRaisesRegex(ValueError, "five-field UTC cron"):
            compile_manifest(manifest, EXAMPLE_MANIFEST_PATH)

        manifest["schedule"]["cronExpressionUtc"] = "30 10 * * MON-FRI"
        with self.assertRaisesRegex(ValueError, "five-field UTC cron"):
            compile_manifest(manifest, EXAMPLE_MANIFEST_PATH)

    def test_rejects_unimplemented_secret_mapping(self):
        manifest = json.loads(EXAMPLE_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["secretReferences"] = [
            {
                "name": "database-password",
                "keyVaultSecretUri": "https://example.vault.azure.net/secrets/password",
                "environmentVariable": "DATABASE_PASSWORD",
            }
        ]

        with self.assertRaisesRegex(ValueError, "secretReferences deployment"):
            compile_manifest(manifest, EXAMPLE_MANIFEST_PATH)

    def test_check_contract_detects_stale_content(self):
        from batchjobs_deploy.compiler import main

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "jobs.parameters.json"
            output.write_text("{}\n", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "is stale"):
                main(
                    [
                        "--jobs-directory",
                        str(ROOT / "jobs"),
                        "--output",
                        str(output),
                        "--check",
                    ]
                )


if __name__ == "__main__":
    unittest.main()