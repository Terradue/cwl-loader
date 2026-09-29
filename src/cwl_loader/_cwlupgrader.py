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

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cwlupgrader.main as _upgrader
from ruamel.yaml.comments import CommentedMap

_CWL_VERSION = "cwlVersion"


def _skip_process_imports(*_args: Any, **_kwargs: Any) -> None:
    """Leave imports for the CWL parser to resolve."""


_upgrader.process_imports = _skip_process_imports


def _to_commented_yaml(value: Any) -> Any:
    if isinstance(value, Mapping):
        return CommentedMap((key, _to_commented_yaml(item)) for key, item in value.items())
    if isinstance(value, list):
        return [_to_commented_yaml(item) for item in value]
    return value


def _upgrade_output_dir(uri: str) -> str:
    parsed_uri = urlparse(uri)
    if parsed_uri.scheme == "file":
        return str(Path(parsed_uri.path).parent)
    if not parsed_uri.scheme:
        return str(Path(uri).parent)
    return "."


def _upgrade_document(
    raw_process: Mapping[str, Any] | CommentedMap,
    cwl_version: str,
    uri: str,
) -> CommentedMap:
    document = deepcopy(raw_process)
    if not isinstance(document, CommentedMap):
        document = _to_commented_yaml(document)

    upgraded = _upgrader.upgrade_document(
        document,
        output_dir=_upgrade_output_dir(uri),
        target_version=cwl_version,
    )
    if not isinstance(upgraded, CommentedMap):
        raise ValueError(
            f"Cannot upgrade CWL document from {raw_process[_CWL_VERSION]} to {cwl_version}"
        )
    return upgraded
