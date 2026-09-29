import sys
from io import StringIO
from pathlib import Path
from unittest import TestCase

from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader import dump_cwl, load_cwl_from_yaml


class MetadataPreservationTests(TestCase):
    def setUp(self) -> None:
        self.yaml = YAML()

    def test_graph_document_metadata_is_dumped_at_document_level(self) -> None:
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
                    "s:softwareVersion": "2.0",
                    "baseCommand": "echo",
                    "inputs": [],
                    "outputs": [],
                },
            ],
        }

        process = load_cwl_from_yaml(raw_process, sort=False)

        assert isinstance(process, list)
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
        self.assertTrue(
            any(
                item.get("https://schema.org/softwareVersion") == "2.0" for item in dumped["$graph"]
            )
        )

    def test_single_item_graph_metadata_keeps_graph_envelope_on_dump(self) -> None:
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

    def test_single_process_document_metadata_is_preserved(self) -> None:
        raw_process = {
            "cwlVersion": "v1.2",
            "$namespaces": {"s": "https://schema.org/"},
            "$schemas": ["https://example.com/schema"],
            "s:softwareVersion": "1.0",
            "class": "CommandLineTool",
            "id": "tool",
            "label": "Original label",
            "baseCommand": "echo",
            "inputs": [],
            "outputs": [],
        }

        process = load_cwl_from_yaml(raw_process, sort=False)
        assert not isinstance(process, list)

        self.assertEqual("1.0", process.loadingOptions.addl_metadata["s:softwareVersion"])
        self.assertEqual(
            {"s": "https://schema.org/"},
            process.loadingOptions.addl_metadata["$namespaces"],
        )

        process.label = "Updated label"
        stream = StringIO()
        dump_cwl(process, stream)
        dumped = self.yaml.load(stream.getvalue())

        self.assertNotIn("$graph", dumped)
        self.assertEqual("Updated label", dumped["label"])
        self.assertEqual("1.0", dumped["s:softwareVersion"])
        self.assertNotIn("https://schema.org/softwareVersion", dumped)
        self.assertEqual({"s": "https://schema.org/"}, dumped["$namespaces"])
        self.assertEqual(["https://example.com/schema"], dumped["$schemas"])

    def test_v1_1_document_is_upgraded_without_mutating_input(self) -> None:
        raw_process = {
            "cwlVersion": "v1.1",
            "class": "CommandLineTool",
            "id": "tool",
            "baseCommand": "echo",
            "inputs": [],
            "outputs": [],
        }

        process = load_cwl_from_yaml(raw_process, sort=False)
        stream = StringIO()
        dump_cwl(process, stream)
        dumped = self.yaml.load(stream.getvalue())

        self.assertEqual("v1.1", raw_process["cwlVersion"])
        self.assertEqual("v1.2", dumped["cwlVersion"])
