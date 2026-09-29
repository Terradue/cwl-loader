# Copyright 2025 Terradue
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Order CWL graphs and workflow steps by their dependencies."""

from __future__ import annotations

from typing import TYPE_CHECKING

from cwl_utils.parser import Workflow

from .utils import to_index

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from cwl_utils.parser import Process

# ---- Utilities --------------------------------------------------------------


def _kahn_toposort(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> list[str]:
    """Order known nodes by dependency, ignoring external edges and duplicates.

    Raises:
        ValueError: If the known nodes contain a dependency cycle.
    """
    nodes = set(nodes)
    succ: Mapping[str, set[str]] = {n: set() for n in nodes}
    pred_count: dict[str, int] = dict.fromkeys(nodes, 0)
    for producer, consumer in set(edges):
        if producer not in nodes or consumer not in nodes:
            # Ignore edges to unknown nodes (e.g., external tools not in $graph)
            continue
        succ[producer].add(consumer)
        pred_count[consumer] += 1

    ready = [node for node in nodes if pred_count[node] == 0]
    ordered: list[str] = []
    while ready:
        node = ready.pop()
        ordered.append(node)
        for successor in succ[node]:
            pred_count[successor] -= 1
            if pred_count[successor] == 0:
                ready.append(successor)

    if any(pred_count[n] > 0 for n in nodes):
        cyclic = [n for n in nodes if pred_count[n] > 0]
        raise ValueError(f"Cycle detected among: {cyclic}")
    return ordered


# ---- Global $graph ordering -------------------------------------------------


def order_graph_by_dependencies(processes: list[Process]) -> list[Process]:
    """Return processes ordered so referenced runs precede their workflows.

    Workflow steps are also sorted in place by their input dependencies.

    Raises:
        ValueError: If the process graph or workflow steps contain a cycle.
    """
    by_id: Mapping[str, Process] = to_index(processes)

    edges: list[tuple[str, str]] = []
    for process in processes:
        # We only add edges from step.run -> workflow.id
        if isinstance(process, Workflow) and process.steps:
            _order_workflow_steps(process)

            workflow_id = process.id
            for step in getattr(process, "steps", []):
                run = getattr(step, "run", None)
                run_id: str | None
                if isinstance(run, str):
                    run_id = run
                else:
                    # Embedded process object
                    embedded_id = getattr(run, "id", None)
                    run_id = embedded_id if isinstance(embedded_id, str) else None
                if run_id:
                    edges.append((run_id, workflow_id))

    sorted_ids = _kahn_toposort(by_id.keys(), edges)
    return [by_id[i] for i in sorted_ids if i in by_id]


# ---- Per-workflow step ordering --------------------------------------------


def _order_workflow_steps(workflow: Workflow) -> None:
    """Sort workflow steps in place so producers precede their consumers.

    Raises:
        ValueError: If workflow steps contain a dependency cycle.
    """
    by_id = to_index(workflow.steps)
    edges: list[tuple[str, str]] = []

    for step in workflow.steps:
        for parameter in step.in_:
            sources = parameter.source or []
            if isinstance(sources, str):
                sources = [sources]
            edges.extend((source.split("/", 1)[0], step.id) for source in sources)

    sorted_steps = _kahn_toposort(by_id.keys(), edges)
    workflow.steps = [by_id[identifier] for identifier in sorted_steps]
