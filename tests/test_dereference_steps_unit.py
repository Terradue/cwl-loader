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

from unittest import TestCase
from unittest.mock import Mock

from cwl_utils.parser.cwl_v1_2 import (
    CommandLineTool,
    Workflow,
    WorkflowInputParameter,
    WorkflowOutputParameter,
    WorkflowStep,
    WorkflowStepInput,
)

from cwl_loader._dereference import _dereference_steps, remove_refs


class TestDereferenceSteps(TestCase):
    def test_remove_refs_normalizes_ids_sources_and_extension_fields(self) -> None:
        step = WorkflowStep(
            id="workflow/stepA",
            in_=[WorkflowStepInput(id="workflow/stepA/in", source="#workflow/producer/out")],
            out=["workflow/stepA/out"],
            run="#workflow/toolA",
            scatter=["#workflow/producer/out"],
        )
        workflow = Workflow(
            id="#workflow",
            inputs=[WorkflowInputParameter(id="workflow/in", type_="string")],
            outputs=[
                WorkflowOutputParameter(
                    id="workflow/out", type_="string", outputSource="#workflow/stepA/out"
                )
            ],
            steps=[step],
            extension_fields={"http://commonwl.org/cwltool#original_cwlVersion": "v1.0"},
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

    def test_external_process_with_existing_id_raises_exception(self) -> None:
        external_url = "https://example.test/external.cwl"

        for process_type in (Workflow, CommandLineTool):
            process_class = process_type.__name__
            with self.subTest(process_class=process_class):
                step = WorkflowStep(id="external-step", in_=[], out=[], run=external_url)
                embedding_workflow = Workflow(id="main", inputs=[], outputs=[], steps=[step])
                existing_process = (
                    Workflow(id="already-included", inputs=[], outputs=[], steps=[])
                    if process_type is Workflow
                    else CommandLineTool(id="already-included", inputs=[], outputs=[])
                )
                imported_process = (
                    Workflow(id="already-included", inputs=[], outputs=[], steps=[])
                    if process_type is Workflow
                    else CommandLineTool(id="already-included", inputs=[], outputs=[])
                )

                with self.assertRaisesRegex(
                    Exception,
                    rf"Cannot import {process_class} already-included .*'id' already present",
                ):
                    _dereference_steps(
                        process=[embedding_workflow, existing_process],
                        uri="https://example.test/main.cwl",
                        session=Mock(),
                        loader=Mock(return_value=imported_process),
                    )
