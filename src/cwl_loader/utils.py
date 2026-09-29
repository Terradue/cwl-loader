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

"""Look up CWL processes and validate graph references."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from cwl_utils.parser import Workflow

if TYPE_CHECKING:
    from collections.abc import Mapping

    from cwl_utils.parser import Process

T = TypeVar("T")


def to_index(collection: list[T]) -> Mapping[str, T]:
    result: dict[str, T] = {}

    for item in collection:
        id = getattr(item, "id", None)
        if id:
            result[id] = item

    return result


def search_process(process_id: str, process: Process | list[Process]) -> Process | None:
    if isinstance(process, list):
        for wf in process:
            if process_id == wf.id:
                return wf
    elif process_id == process.id:
        return process

    return None


def contains_process(process_id: str, process: Process | list[Process]) -> bool:
    return search_process(process_id=process_id, process=process) is not None


def get_ids(process: Process | list[Process]) -> list[str]:
    return [p.id for p in process] if isinstance(process, list) else [process.id]


def assert_process_contained(process_id: str, process: Process | list[Process]) -> None:
    """Require the requested process to exist.

    Raises:
        ValueError: If the document does not contain the requested identifier.
    """
    if not contains_process(process_id=process_id, process=process):
        raise ValueError(
            f"Process {process_id} does not exist in input CWL document, only {get_ids(process)} available."
        )


def assert_connected_graph(process: Process | list[Process]) -> None:
    """Require all workflow run references to resolve within the graph.

    Raises:
        ValueError: If any workflow step references a missing process.
    """
    index: Mapping[str, Process] = (
        to_index(process) if isinstance(process, list) else {process.id: process}
    )
    issues: list[str] = []

    for current in index.values():
        if isinstance(current, Workflow):
            issues.extend(
                f"- {current.id}.steps.{step.id} = {step.run}"
                for step in current.steps
                if isinstance(step.run, str) and not index.get(step.run[1:])
            )

    if issues:
        nl = "\n"
        raise ValueError(f"Detected unresolved links in the input $graph:\n{nl.join(issues)}")
