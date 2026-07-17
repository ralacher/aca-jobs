import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "job-manifest.schema.json"


class ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(
            cls.schema,
            format_checker=FormatChecker(),
        )

    def test_all_job_manifests_match_schema_and_reference_local_scripts(self):
        manifest_paths = sorted((ROOT / "jobs").glob("*/job.json"))
        self.assertTrue(manifest_paths, "At least one job manifest is required")

        job_ids = set()
        for manifest_path in manifest_paths:
            with self.subTest(manifest=manifest_path):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.validator.validate(manifest)
                self.assertNotIn(manifest["id"], job_ids)
                job_ids.add(manifest["id"])

                job_directory = manifest_path.parent.resolve()
                script_path = (job_directory / manifest["runtime"]["script"]).resolve()
                self.assertTrue(script_path.is_relative_to(job_directory))
                self.assertTrue(script_path.is_file())


if __name__ == "__main__":
    unittest.main()