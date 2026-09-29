import sys
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest import TestCase

from cwl_utils.parser.cwl_v1_2 import CommandLineTool, Workflow, WorkflowStep

if TYPE_CHECKING:
    from cwl_utils.parser import Process


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader.utils import (
    assert_connected_graph,
    assert_process_contained,
    contains_process,
    search_process,
    to_index,
)


class UtilsUnitTests(TestCase):
    def test_to_index_skips_items_without_id(self) -> None:
        proc1 = SimpleNamespace(id="a")
        proc2 = SimpleNamespace(id="b")
        no_id = SimpleNamespace()

        result = to_index([proc1, no_id, proc2])

        self.assertEqual({"a": proc1, "b": proc2}, result)

    def test_search_and_contains_process(self) -> None:
        proc1 = CommandLineTool(id="wf", inputs=[], outputs=[])
        proc2 = CommandLineTool(id="tool", inputs=[], outputs=[])
        graph: list[Process] = [proc1, proc2]

        self.assertIs(search_process("wf", graph), proc1)
        self.assertIs(search_process("tool", proc2), proc2)
        self.assertIsNone(search_process("missing", graph))
        self.assertTrue(contains_process("wf", graph))
        self.assertFalse(contains_process("missing", graph))

    def test_assert_process_contained_raises_for_missing_process(self) -> None:
        graph: list[Process] = [CommandLineTool(id="wf", inputs=[], outputs=[])]

        with self.assertRaises(ValueError) as ctx:
            assert_process_contained("missing", graph)

        self.assertIn("Process missing does not exist", str(ctx.exception))

    def test_assert_connected_graph_reports_unresolved_runs(self) -> None:
        workflow = Workflow(
            id="wf",
            inputs=[],
            outputs=[],
            steps=[WorkflowStep(id="s1", in_=[], out=[], run="#tool")],
        )

        with self.assertRaises(ValueError) as ctx:
            assert_connected_graph([workflow])

        self.assertIn("wf.steps.s1 = #tool", str(ctx.exception))

    def test_assert_connected_graph_passes_when_all_links_are_resolved(self) -> None:
        workflow = Workflow(
            id="wf",
            inputs=[],
            outputs=[],
            steps=[WorkflowStep(id="s1", in_=[], out=[], run="#tool")],
        )
        tool = CommandLineTool(id="tool", inputs=[], outputs=[])

        assert_connected_graph([workflow, tool])
