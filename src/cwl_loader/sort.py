"""
The CWL Loader Python library is a helper library to simplify the parse and serialize operations of CWL documents to and from [cwl-utils](https://github.com/common-workflow-language/cwl-utils) object models.

CWL Loader (c) 2025

CWL Loader is licensed under
Creative Commons Attribution-ShareAlike 4.0 International.

You should have received a copy of the license along with this work.
If not, see <https://creativecommons.org/licenses/by-sa/4.0/>.
"""

from cwl_utils.parser import (
    Process,
    Workflow
)
from typing import (
    Dict,
    Iterable,
    List,
    Tuple,
    Set
)

# ---- Utilities --------------------------------------------------------------

def _kahn_toposort(nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> List[str]:
    """Return a topo-sorted list of node ids. Raises ValueError on cycles."""
    nodes = set(nodes)
    succ: Dict[str, Set[str]] = {n: set() for n in nodes}
    pred_count: Dict[str, int] = {n: 0 for n in nodes}
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
    processes: Iterable[Process]
) -> List[Process]:
    """
    Sort top-level parsed objects so that any process referenced by a Workflow step.run
    appears before the Workflow that uses it.
    """
    by_id: Dict[str, Process] = {}
    nodes: Set[str] = set()

    for process in processes:
        pid = getattr(process, "id", None)
        if not pid:
            continue
        by_id[pid] = process
        nodes.add(pid)

    edges: List[Tuple[str, str]] = []
    for process in processes:
        # We only add edges from step.run -> workflow.id
        clsname = type(process).__name__
        if clsname.endswith("Workflow") and getattr(process, "steps", None):
            _order_workflow_steps(process) # type: ignore

            workflow_id = process.id
            for st in process.steps:
                run = getattr(st, "run", None)
                if isinstance(run, str):
                    rid = run
                else:
                    # Embedded process object
                    rid = getattr(getattr(run, "__dict__", {}), "id", getattr(run, "id", "")) or None
                if rid:
                    edges.append((rid, workflow_id))

    sorted_ids = _kahn_toposort(nodes, edges)
    return [by_id[i] for i in sorted_ids if i in by_id]

# ---- Per-workflow step ordering --------------------------------------------

def _order_workflow_steps(
    workflow: Workflow
):
    """
    Sort steps within a Workflow so that data dependencies (in[].source) are respected.
    """
    by_id: Dict[str, object] = {}
    sid_nodes: Set[str] = set()
    edges: List[Tuple[str, str]] = []

    # Collect node ids
    for step in workflow.steps:
        sid_nodes.add(step.id)
        by_id[step.id] = step

    # Add edges from producer -> consumer based on in[].source
    for step in workflow.steps:
        if not getattr(step, "in_", None):   # note: in_ because 'in' is reserved in Python; cwlutils uses in_ in some versions
            # Some versions keep the field as 'inputs' or 'in'; support both:
            sources = []
        else:
            sources = workflow.__dict__.get("in_", None)

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
                    if producer in sid_nodes:
                        edges.append((producer, step.id))

    sorted_steps = _kahn_toposort(sid_nodes, edges)
    workflow.steps = [by_id[i] for i in sorted_steps if i in by_id]
