from io import StringIO
from pathlib import Path
from unittest import TestCase
import sys

from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader import dump_cwl, load_cwl_from_yaml


class MetadataPreservationTests(TestCase):
    def setUp(self):
        self.yaml = YAML()

    def test_graph_document_metadata_is_dumped_at_document_level(self):
        raw_process = {
            "cwlVersion": "v1.2",
            "$namespaces": {"s": "https://schema.org/"},
            "metadata": {"owner": "team"},
            "s:softwareVersion": "1.0",
            "$graph": [
                {
                    "class": "Workflow",
                    "id": "main",
                    "inputs": [],
                    "outputs": [],
                    "steps": {
                        "echo": {
                            "in": [],
                            "out": [],
                            "run": "#tool",
                        }
                    },
                },
                {
                    "class": "CommandLineTool",
                    "id": "tool",
                    "baseCommand": "echo",
                    "inputs": [],
                    "outputs": [],
                },
            ],
        }

        process = load_cwl_from_yaml(raw_process, sort=False)

        self.assertIsInstance(process, list)
        self.assertEqual(
            {"owner": "team"},
            process[0].loadingOptions.addl_metadata["metadata"],
        )

        stream = StringIO()
        dump_cwl(process, stream)

        dumped = self.yaml.load(stream.getvalue())

        self.assertEqual({"owner": "team"}, dumped["metadata"])
        self.assertEqual("1.0", dumped["s:softwareVersion"])
        self.assertEqual({"s": "https://schema.org/"}, dumped["$namespaces"])
        self.assertIn("$graph", dumped)
        self.assertNotIn("metadata", dumped["$graph"][0])
        self.assertNotIn("$namespaces", dumped["$graph"][0])

    def test_single_item_graph_metadata_keeps_graph_envelope_on_dump(self):
        raw_process = {
            "cwlVersion": "v1.2",
            "metadata": {"owner": "team"},
            "$graph": [
                {
                    "class": "CommandLineTool",
                    "id": "tool",
                    "baseCommand": "echo",
                    "inputs": [],
                    "outputs": [],
                }
            ],
        }

        process = load_cwl_from_yaml(raw_process, sort=False)
        stream = StringIO()

        dump_cwl(process, stream)

        dumped = self.yaml.load(stream.getvalue())

        self.assertEqual({"owner": "team"}, dumped["metadata"])
        self.assertIn("$graph", dumped)
        self.assertEqual("tool", dumped["$graph"][0]["id"])
