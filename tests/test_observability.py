import json
import unittest
from pathlib import Path

from batchjobs_deploy.compiler import compile_directory

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "infra" / "observability" / "workbook.json"


class ObservabilityTests(unittest.TestCase):
    def test_workbook_has_expected_fleet_panels_and_workspace_placeholders(self):
        source = WORKBOOK_PATH.read_text(encoding="utf-8")
        workbook = json.loads(source)

        self.assertEqual("Notebook/1.0", workbook["version"])
        self.assertEqual(["__WORKSPACE_ID__"], workbook["fallbackResourceIds"])

        item_names = {item["name"] for item in workbook["items"]}
        self.assertTrue(
            {
                "parameters",
                "fleet-summary",
                "latest-status",
                "duration-trend",
                "failures",
                "console-output",
            }.issubset(item_names)
        )
        self.assertGreater(source.count("__WORKSPACE_ID__"), 1)
        self.assertIn("batchjobs.lifecycle.v1", source)

        parameter_item = next(
            item for item in workbook["items"] if item["name"] == "parameters"
        )["content"]
        job_parameter = next(
            parameter
            for parameter in parameter_item["parameters"]
            if parameter["name"] == "Job"
        )
        self.assertEqual(0, parameter_item["queryType"])
        self.assertEqual(
            "microsoft.operationalinsights/workspaces",
            parameter_item["resourceType"],
        )
        self.assertEqual(["__WORKSPACE_ID__"], parameter_item["crossComponentResources"])
        self.assertEqual(0, job_parameter["queryType"])
        self.assertEqual(
            "microsoft.operationalinsights/workspaces",
            job_parameter["resourceType"],
        )
        self.assertEqual(["__WORKSPACE_ID__"], job_parameter["crossComponentResources"])

    def test_compiled_jobs_include_monitoring_policy(self):
        document = compile_directory(ROOT / "jobs")
        definition = document["parameters"]["jobDefinitions"]["value"][0]

        self.assertEqual(
            {
                "alertOnFailure": True,
                "alertOnOverlap": False,
                "alertOnStale": False,
                "maxSilenceMinutes": 1440,
            },
            definition["monitoring"],
        )


if __name__ == "__main__":
    unittest.main()
