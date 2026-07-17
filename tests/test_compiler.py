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

        self.assertIn("parameters", document)
        self.assertIn("jobDefinitions", document["parameters"])
        definitions = document["parameters"]["jobDefinitions"]["value"]
        self.assertIsInstance(definitions, list)
        self.assertGreater(len(definitions), 0)

        required_keys = {
            "arguments",
            "cpu",
            "cronExpressionUtc",
            "enabled",
            "environment",
            "id",
            "memory",
            "monitoring",
            "retryLimit",
            "script",
            "timeoutSeconds",
        }
        required_monitoring_keys = {
            "alertOnFailure",
            "alertOnOverlap",
            "alertOnStale",
            "maxSilenceMinutes",
        }

        for definition in definitions:
            self.assertTrue(required_keys.issubset(definition.keys()))
            self.assertIsInstance(definition["id"], str)
            self.assertNotEqual(definition["id"].strip(), "")
            self.assertTrue(
                definition["script"].startswith(f"/app/jobs/{definition['id']}/")
            )

            self.assertIsInstance(definition["monitoring"], dict)
            self.assertTrue(
                required_monitoring_keys.issubset(definition["monitoring"].keys())
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