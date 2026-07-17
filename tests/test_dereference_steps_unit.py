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

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from cwl_loader import _dereference_steps


class TestDereferenceSteps(TestCase):
    def test_external_process_with_existing_id_raises_exception(self):
        external_url = "https://example.test/external.cwl"

        for process_class in ("Workflow", "CommandLineTool"):
            with self.subTest(process_class=process_class):
                step = SimpleNamespace(id="external-step", run=external_url)
                embedding_workflow = SimpleNamespace(
                    id="main", class_="Workflow", steps=[step]
                )
                existing_process = SimpleNamespace(
                    id="already-included", class_=process_class, steps=[]
                )
                imported_process = SimpleNamespace(
                    id="already-included", class_=process_class, steps=[]
                )

                with patch(
                    "cwl_loader.load_cwl_from_location",
                    return_value=imported_process,
                ):
                    with self.assertRaisesRegex(
                        Exception,
                        rf"Cannot import {process_class} already-included .*'id' already present",
                    ):
                        _dereference_steps(
                            process=[embedding_workflow, existing_process],
                            uri="https://example.test/main.cwl",
                            session=SimpleNamespace(),
                        )
