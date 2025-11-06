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

# This workflow will install Python dependencies, run tests and lint with a single version of Python
# For more information see: https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python

from .utils import to_index
from cwl_utils.parser import (
    Process,
    Workflow
)
from typing import (
    Iterable,
    List,
    Mapping,
    Tuple,
    Set
)

# ---- Utilities --------------------------------------------------------------

def _kahn_toposort(
    nodes: Iterable[str],
    edges: Iterable[Tuple[str, str]]
) -> List[str]:
    """Return a topo-sorted list of node ids. Raises ValueError on cycles."""
    nodes = set(nodes)
    succ: Mapping[str, Set[str]] = {n: set() for n in nodes}
    pred_count: Mapping[str, int] = {n: 0 for n in nodes}
    for a, b in edges:
        if a not in nodes or b not in nodes:
            # Ignore edges to unknown nodes (e.g., external tools not in $graph)
            continue
        if b not in succ[a]:
            succ[a].add(b)
            pred_count[b] += 1

    S = [n for n in nodes if pred_count[n] == 0]
    out: List[str] = []
    while S:
        n = S.pop()
        out.append(n)
        for m in list(succ[n]):
            succ[n].remove(m)
            pred_count[m] -= 1
            if pred_count[m] == 0:
                S.append(m)

    if any(pred_count[n] > 0 for n in nodes):
        cyclic = [n for n in nodes if pred_count[n] > 0]
        raise ValueError(f"Cycle detected among: {cyclic}")
    return out

# ---- Global $graph ordering -------------------------------------------------

def order_graph_by_dependencies(
    processes: List[Process]
) -> List[Process]:
    """
    Sort top-level parsed objects so that any process referenced by a Workflow step.run
    appears before the Workflow that uses it.
    """
    by_id: Mapping[str, Process] = to_index(processes)

    edges: List[Tuple[str, str]] = []
    for process in processes:
        # We only add edges from step.run -> workflow.id
        class_name = type(process).__name__
        if class_name.endswith("Workflow") and getattr(process, "steps", None):
            _order_workflow_steps(process) # type: ignore

            workflow_id = process.id
            for step in getattr(process, "steps", []):
                run = getattr(step, "run", None)
                if isinstance(run, str):
                    run_id = run
                else:
                    # Embedded process object
                    run_id = getattr(getattr(run, "__dict__", {}), "id", getattr(run, "id", "")) or None
                if run_id:
                    edges.append((run_id, workflow_id))

    sorted_ids = _kahn_toposort(by_id.keys(), edges)
    return [by_id[i] for i in sorted_ids if i in by_id]

# ---- Per-workflow step ordering --------------------------------------------

def _order_workflow_steps(
    workflow: Workflow
):
    """
    Sort steps within a Workflow so that data dependencies (in[].source) are respected.
    """
    by_id: Mapping[str, object] = to_index(workflow.steps)
    edges: List[Tuple[str, str]] = []

    # Add edges from producer -> consumer based on in[].source
    for step in workflow.steps:
        # Compatible access across versions:
        inputs = getattr(step, "in_", None) or getattr(step, "inputs", None) or getattr(step, "in", None)
        if inputs:
            for inp in inputs:
                srcs = getattr(inp, "source", None)
                if not srcs:
                    continue
                # source can be str or List[str]
                if isinstance(srcs, str):
                    srcs = [srcs]
                for s in srcs:
                    # sources are like "stepId/outputName" or "#wf/stepId/output"
                    # Extract the stepId (token before the first '/'), ignoring external ports
                    producer = s.split("/", 1)[0]
                    if producer in by_id.keys():
                        edges.append((producer, step.id))

    sorted_steps = _kahn_toposort(by_id.keys(), edges)
    workflow.steps = [by_id[i] for i in sorted_steps if i in by_id]
