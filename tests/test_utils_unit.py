from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader.utils import (
    assert_connected_graph,
    assert_process_contained,
    contains_process,
    remove_refs,
    search_process,
    to_index,
)


class FakeWorkflow:
    def __init__(self, process_id, steps):
        self.id = process_id
        self.steps = steps


class UtilsUnitTests(TestCase):
    def test_to_index_skips_items_without_id(self):
        proc1 = SimpleNamespace(id="a")
        proc2 = SimpleNamespace(id="b")
        no_id = SimpleNamespace()

        result = to_index([proc1, no_id, proc2])

        self.assertEqual({"a": proc1, "b": proc2}, result)

    def test_search_and_contains_process(self):
        proc1 = SimpleNamespace(id="wf")
        proc2 = SimpleNamespace(id="tool")
        graph = [proc1, proc2]

        self.assertIs(search_process("wf", graph), proc1)
        self.assertIs(search_process("tool", proc2), proc2)
        self.assertIsNone(search_process("missing", graph))
        self.assertTrue(contains_process("wf", graph))
        self.assertFalse(contains_process("missing", graph))

    def test_assert_process_contained_raises_for_missing_process(self):
        graph = [SimpleNamespace(id="wf")]

        with self.assertRaises(ValueError) as ctx:
            assert_process_contained("missing", graph)

        self.assertIn("Process missing does not exist", str(ctx.exception))

    def test_remove_refs_normalizes_ids_sources_and_extension_fields(self):
        step = SimpleNamespace(
            id="workflow/stepA",
            in_=[
                SimpleNamespace(id="workflow/stepA/in", source="#workflow/producer/out")
            ],
            out=["workflow/stepA/out"],
            run="#workflow/toolA",
            scatter=["#workflow/producer/out"],
        )
        workflow = SimpleNamespace(
            id="#workflow",
            inputs=[SimpleNamespace(id="workflow/in")],
            outputs=[
                SimpleNamespace(id="workflow/out", outputSource="#workflow/stepA/out")
            ],
            steps=[step],
            extension_fields={
                "http://commonwl.org/cwltool#original_cwlVersion": "v1.0"
            },
        )

        remove_refs([workflow])

        self.assertEqual("workflow", workflow.id)
        self.assertEqual("in", workflow.inputs[0].id)
        self.assertEqual("out", workflow.outputs[0].id)
        self.assertEqual("stepA/out", workflow.outputs[0].outputSource)
        self.assertEqual("stepA", step.id)
        self.assertEqual("in", step.in_[0].id)
        self.assertEqual("producer/out", step.in_[0].source)
        self.assertEqual(["out"], step.out)
        self.assertEqual("#workflow/toolA", step.run)
        self.assertEqual(["producer/out"], step.scatter)
        self.assertEqual({}, workflow.extension_fields)

    def test_assert_connected_graph_reports_unresolved_runs(self):
        workflow = FakeWorkflow(
            process_id="wf",
            steps=[SimpleNamespace(id="s1", run="#tool")],
        )

        with patch("cwl_loader.utils.get_args", return_value=(FakeWorkflow,)):
            with self.assertRaises(ValueError) as ctx:
                assert_connected_graph([workflow])

        self.assertIn("wf.steps.s1 = #tool", str(ctx.exception))

    def test_assert_connected_graph_passes_when_all_links_are_resolved(self):
        workflow = FakeWorkflow(
            process_id="wf",
            steps=[SimpleNamespace(id="s1", run="#tool")],
        )
        tool = SimpleNamespace(id="tool")

        with patch("cwl_loader.utils.get_args", return_value=(FakeWorkflow,)):
            assert_connected_graph([workflow, tool])
