import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest import TestCase

from cwl_utils.parser.cwl_v1_2 import CommandLineTool, Workflow, WorkflowStep, WorkflowStepInput

if TYPE_CHECKING:
    from cwl_utils.parser import Process


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader.sort import (
    _kahn_toposort,
    _order_workflow_steps,
    order_graph_by_dependencies,
)


class SortUnitTests(TestCase):
    def test_kahn_toposort_orders_by_dependencies(self) -> None:
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]

        result = _kahn_toposort(nodes, edges)

        self.assertLess(result.index("A"), result.index("B"))
        self.assertLess(result.index("B"), result.index("C"))

    def test_kahn_toposort_detects_cycles(self) -> None:
        nodes = ["A", "B"]
        edges = [("A", "B"), ("B", "A")]

        with self.assertRaises(ValueError) as ctx:
            _kahn_toposort(nodes, edges)

        self.assertIn("Cycle detected", str(ctx.exception))

    def test_order_workflow_steps_uses_input_sources(self) -> None:
        producer = WorkflowStep(id="producer", in_=[], out=[], run="#tool")
        consumer = WorkflowStep(
            out=[],
            run="#tool",
            id="consumer",
            in_=[WorkflowStepInput(id="consumer/in", source="producer/out")],
        )
        workflow = Workflow(id="wf", inputs=[], outputs=[], steps=[consumer, producer])

        _order_workflow_steps(workflow)

        self.assertEqual(["producer", "consumer"], [s.id for s in workflow.steps])

    def test_order_graph_by_dependencies_places_tools_before_workflows(self) -> None:
        step = WorkflowStep(id="step1", in_=[], out=[], run="toolA")
        workflow = Workflow(id="wf", inputs=[], outputs=[], steps=[step])
        tool = CommandLineTool(id="toolA", inputs=[], outputs=[])
        graph: list[Process] = [workflow, tool]

        ordered = order_graph_by_dependencies(graph)

        self.assertEqual(["toolA", "wf"], [p.id for p in ordered])

    def test_kahn_toposort_ignores_duplicate_and_external_edges(self) -> None:
        result = _kahn_toposort(
            ["producer", "consumer"],
            [("producer", "consumer"), ("producer", "consumer"), ("external", "consumer")],
        )

        self.assertEqual(["producer", "consumer"], result)

    def test_order_workflow_steps_accepts_multiple_sources_and_external_inputs(self) -> None:
        producer = WorkflowStep(id="producer", in_=[], out=[], run="#tool")
        consumer = WorkflowStep(
            id="consumer",
            out=[],
            run="#tool",
            in_=[WorkflowStepInput(id="input", source=["producer/out", "workflow_input"])],
        )
        workflow = Workflow(id="workflow", inputs=[], outputs=[], steps=[consumer, producer])

        _order_workflow_steps(workflow)

        self.assertEqual(["producer", "consumer"], [step.id for step in workflow.steps])
