from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cwl_loader.sort import (
    _kahn_toposort,
    _order_workflow_steps,
    order_graph_by_dependencies,
)


class DemoWorkflow:
    def __init__(self, process_id, steps):
        self.id = process_id
        self.steps = steps


class SortUnitTests(TestCase):
    def test_kahn_toposort_orders_by_dependencies(self):
        nodes = ["A", "B", "C"]
        edges = [("A", "B"), ("B", "C")]

        result = _kahn_toposort(nodes, edges)

        self.assertLess(result.index("A"), result.index("B"))
        self.assertLess(result.index("B"), result.index("C"))

    def test_kahn_toposort_detects_cycles(self):
        nodes = ["A", "B"]
        edges = [("A", "B"), ("B", "A")]

        with self.assertRaises(ValueError) as ctx:
            _kahn_toposort(nodes, edges)

        self.assertIn("Cycle detected", str(ctx.exception))

    def test_order_workflow_steps_uses_input_sources(self):
        producer = SimpleNamespace(id="producer", in_=[])
        consumer = SimpleNamespace(
            id="consumer",
            in_=[SimpleNamespace(id="consumer/in", source="producer/out")],
        )
        workflow = DemoWorkflow("wf", [consumer, producer])

        _order_workflow_steps(workflow)

        self.assertEqual(["producer", "consumer"], [s.id for s in workflow.steps])

    def test_order_graph_by_dependencies_places_tools_before_workflows(self):
        step = SimpleNamespace(id="step1", in_=[], run="toolA")
        workflow = DemoWorkflow("wf", [step])
        tool = SimpleNamespace(id="toolA")
        graph = [workflow, tool]

        ordered = order_graph_by_dependencies(graph)

        self.assertEqual(["toolA", "wf"], [p.id for p in ordered])
