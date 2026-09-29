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

"""Regression coverage for inline DOM runs and local file URI loading."""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from cwl_utils.parser.cwl_v1_2 import CommandLineTool, Workflow, WorkflowStep

if TYPE_CHECKING:
    from pathlib import Path

    from cwl_utils.parser import Process


from cwl_loader import dump_cwl, load_cwl_from_location, load_cwl_from_string_content
from cwl_loader._dereference import _dereference_steps

TOOL = """class: CommandLineTool
inputs: {message: string}
outputs: {result: {type: File, outputBinding: {glob: result.txt}}}
baseCommand: echo
stdout: result.txt
"""


def workflow(run: str) -> str:
    """Build a workflow document with the supplied run declaration."""
    return (
        "cwlVersion: v1.2\nclass: Workflow\nid: main\n"
        "inputs: {message: string}\n"
        "outputs: {result: {type: File, outputSource: echo/result}}\n"
        "steps:\n  echo:\n    in: {message: message}\n    out: [result]\n" + run
    )


def inline(content: str) -> str:
    """Indent a process document for use as an inline run."""
    return "    run:\n" + "".join(f"      {line}\n" for line in content.splitlines())


def index(result: Process | list[Process]) -> dict[str, Process]:
    """Index loaded processes by their normalized identifiers."""
    return {p.id: p for p in (result if isinstance(result, list) else [result])}


@pytest.mark.parametrize("named", [False, True])
def test_inline_tool(tmp_path: Path, named: bool) -> None:
    text = workflow(inline(("id: tool\n" if named else "") + TOOL))
    path = tmp_path / "main.cwl"
    path.write_text(text)
    processes = index(load_cwl_from_location(str(path)))
    root = processes["main"]
    assert isinstance(root, Workflow)
    tool_id = root.steps[0].run[1:]
    assert tool_id == ("main/echo/run/tool" if named else "main/echo/run")
    assert processes[tool_id].class_ == "CommandLineTool"
    assert root.steps[0].in_[0].source == "message"
    assert root.outputs[0].outputSource == "echo/result"
    stream = StringIO()
    dump_cwl(list(processes.values()), stream)
    assert set(index(load_cwl_from_string_content(stream.getvalue(), uri=path.as_uri()))) == set(
        processes
    )


def test_nested_anonymous_inline_workflow(tmp_path: Path) -> None:
    nested = workflow(inline(TOOL)).replace("cwlVersion: v1.2\n", "").replace("id: main\n", "")
    path = tmp_path / "main.cwl"
    path.write_text(workflow(inline(nested)))
    processes = index(load_cwl_from_location(path.as_uri()))
    expected_process_count = 3
    assert len(processes) == expected_process_count
    root = processes["main"]
    assert isinstance(root, Workflow)
    inner = processes[root.steps[0].run[1:]]
    assert isinstance(inner, Workflow)
    assert inner.class_ == "Workflow"
    assert inner.steps[0].run[1:] in processes
    assert inner.steps[0].in_[0].source == "message"
    assert inner.outputs[0].outputSource == "echo/result"


@pytest.mark.parametrize("location", ["path", "relative", "uri", "localhost", "fragment"])
def test_local_sources_and_relative_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    directory = tmp_path / "space é # %"
    directory.mkdir()
    tool = directory / "tool.cwl"
    tool.write_text("cwlVersion: v1.2\nid: tool\n" + TOOL)
    source = directory / "main.cwl"
    source.write_text(workflow("    run: tool.cwl\n"))
    monkeypatch.chdir(tmp_path)
    locations = {
        "path": str(source),
        "relative": str(source.relative_to(tmp_path)),
        "uri": source.as_uri(),
        "localhost": source.as_uri().replace("file://", "file://localhost"),
        "fragment": source.as_uri() + "#main",
    }
    processes = index(load_cwl_from_location(locations[location]))
    root = processes["main"]
    assert isinstance(root, Workflow)
    assert root.steps[0].run == "#tool"
    assert processes["tool"].class_ == "CommandLineTool"


def test_unsaved_text_retains_base_for_relative_run(tmp_path: Path) -> None:
    (tmp_path / "tool.cwl").write_text("cwlVersion: v1.2\nid: tool\n" + TOOL)
    source = tmp_path / "main.cwl"
    source.write_text(workflow("    run: tool.cwl\n"))
    original = source.read_text()
    processes = index(
        load_cwl_from_string_content(original + "label: unsaved\n", uri=source.as_uri())
    )
    assert processes["main"].label == "unsaved"
    assert source.read_text() == original


@pytest.mark.parametrize(
    "uri, message",
    [
        ("file://server.example/a.cwl", "Non-local file URI authority"),
        ("file:///tmp/a.cwl?query=yes", "File URI queries"),
        ("file:relative.cwl", "absolute path"),
    ],
)
def test_reject_unsupported_file_uris(uri: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_cwl_from_location(uri)


def test_missing_file_uri(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Invalid source"):
        load_cwl_from_location((tmp_path / "missing.cwl").as_uri())


def test_duplicate_inline_ids_rejected() -> None:
    tool1 = CommandLineTool(id="file:///main.cwl#tool", inputs=[], outputs=[])
    tool2 = CommandLineTool(id=tool1.id, inputs=[], outputs=[])
    parent = Workflow(
        inputs=[],
        outputs=[],
        id="main",
        steps=[
            WorkflowStep(id="first", in_=[], out=[], run=tool1),
            WorkflowStep(id="second", in_=[], out=[], run=tool2),
        ],
    )
    with pytest.raises(ValueError, match="Duplicate inline process identifier"):
        _dereference_steps([parent], "file:///main.cwl", Mock(), Mock())
