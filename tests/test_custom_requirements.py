# Copyright 2026 Terradue
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

from io import StringIO
from typing import Any
from unittest import TestCase

from cwl_utils.parser import Process
from ruamel.yaml import YAML

from cwl_loader import (
    _custom_requirements_cache,
    dump_cwl_with_custom_requirements,
    extract_dask_config,
    load_cwl_from_string_content,
)

_yaml = YAML()

# ---------------------------------------------------------------------------
# Minimal valid CWL fixtures
# ---------------------------------------------------------------------------

_SIMPLE_CWL = """\
cwlVersion: v1.2
class: CommandLineTool
id: simple-tool
baseCommand: echo
inputs:
  msg:
    type: string
    inputBinding:
      position: 1
outputs:
  out:
    type: stdout
"""

_GRAPH_CWL_WITH_CUSTOM_REQ = """\
cwlVersion: v1.2
$namespaces:
  calrissian: "http://calrissian.example.com/"
$graph:
- class: CommandLineTool
  id: echo-tool
  baseCommand: echo
  requirements:
    DockerRequirement:
      dockerPull: "alpine:latest"
    calrissian:DaskGatewayRequirement:
      gateway_url: "http://gateway.example.com"
      worker_cores: 2
      worker_memory: "4G"
  inputs:
    message:
      type: string
      inputBinding:
        position: 1
  outputs:
    out:
      type: stdout
- class: Workflow
  id: main
  inputs:
    message:
      type: string
  outputs:
    result:
      type: File
      outputSource: step1/out
  steps:
    step1:
      run: "#echo-tool"
      in:
        message: message
      out: [out]
"""

_SINGLE_CWL_WITH_CUSTOM_REQ = """\
cwlVersion: v1.2
$namespaces:
  calrissian: "http://calrissian.example.com/"
class: CommandLineTool
id: echo-tool
baseCommand: echo
requirements:
  DockerRequirement:
    dockerPull: "alpine:latest"
  calrissian:DaskGatewayRequirement:
    gateway_url: "http://gateway.example.com"
    worker_cores: 2
    worker_memory: "4G"
inputs:
  message:
    type: string
    inputBinding:
      position: 1
outputs:
  out:
    type: stdout
"""


class TestCustomRequirements(TestCase):
    _graph_data: dict[str, Any]
    _single_data: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        process = load_cwl_from_string_content(_GRAPH_CWL_WITH_CUSTOM_REQ)
        out = StringIO()
        dump_cwl_with_custom_requirements(process, out)
        cls._graph_data = _yaml.load(out.getvalue())

        process = load_cwl_from_string_content(_SINGLE_CWL_WITH_CUSTOM_REQ)
        out = StringIO()
        dump_cwl_with_custom_requirements(process, out)
        cls._single_data = _yaml.load(out.getvalue())

    def test_graph_with_custom_req_parses_successfully(self) -> None:
        result = load_cwl_from_string_content(_GRAPH_CWL_WITH_CUSTOM_REQ)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, list)
        assert isinstance(result, list)
        self.assertEqual(2, len(result))

    def test_single_process_with_custom_req_parses_successfully(self) -> None:
        result = load_cwl_from_string_content(_SINGLE_CWL_WITH_CUSTOM_REQ)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Process)

    def test_graph_dump_roundtrip_restores_namespaces(self) -> None:
        self.assertIn("$namespaces", self._graph_data)
        self.assertIn("calrissian", self._graph_data["$namespaces"])

    def test_graph_dump_roundtrip_reinjects_custom_req(self) -> None:
        tool_item = next(
            (item for item in self._graph_data["$graph"] if item.get("class") == "CommandLineTool"),
            None,
        )
        self.assertIsNotNone(tool_item)
        assert tool_item is not None
        reqs = tool_item.get("requirements", [])
        dask_req = [r for r in reqs if "DaskGatewayRequirement" in r.get("class", "")]
        self.assertEqual(1, len(dask_req))

    def test_single_process_dump_roundtrip_reinjects_custom_req(self) -> None:
        reqs = self._single_data.get("requirements", [])
        dask_req = [r for r in reqs if "DaskGatewayRequirement" in r.get("class", "")]
        self.assertEqual(1, len(dask_req))

    def test_extract_dask_config_from_graph(self) -> None:
        load_cwl_from_string_content(_GRAPH_CWL_WITH_CUSTOM_REQ)
        config = extract_dask_config()
        self.assertEqual("http://gateway.example.com", config.get("gateway_url"))
        self.assertEqual(2, config.get("worker_cores"))
        self.assertEqual("4G", config.get("worker_memory"))

    def test_extract_dask_config_from_single_process(self) -> None:
        load_cwl_from_string_content(_SINGLE_CWL_WITH_CUSTOM_REQ)
        config = extract_dask_config()
        self.assertEqual("http://gateway.example.com", config.get("gateway_url"))

    def test_extract_dask_config_with_explicit_cache(self) -> None:
        explicit_cache = {
            "my-tool": {
                "calrissian:DaskGatewayRequirement": {"gateway_url": "http://explicit.example.com"}
            }
        }
        config = extract_dask_config(custom_requirements_cache=explicit_cache)
        self.assertEqual("http://explicit.example.com", config.get("gateway_url"))

    def test_extract_dask_config_returns_empty_when_absent(self) -> None:
        config = extract_dask_config(custom_requirements_cache={})
        self.assertEqual({}, config)

    def test_successive_loads_do_not_leak_cache(self) -> None:
        load_cwl_from_string_content(_SINGLE_CWL_WITH_CUSTOM_REQ)
        self.assertTrue(
            len(_custom_requirements_cache) > 0,
            "Cache should be populated after first load",
        )

        load_cwl_from_string_content(_SIMPLE_CWL)
        self.assertEqual(
            {},
            dict(_custom_requirements_cache),
            "Cache must be empty after loading a doc without custom reqs",
        )
