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
from cwltool.update import ORIGINAL_CWLVERSION
from loguru import logger
from typing import (
    get_args,
    List,
    Mapping,
    TypeVar
)

T = TypeVar('T')

def to_index(
    collection: List[T]
) -> Mapping[str, T]:
    result: Mapping[str, T] = {}

    for item in collection:
        id = getattr(item, 'id', None)
        if id:
            result[id] = item

    return result

def search_process(
    process_id: str,
    process: Process | List[Process]
) -> Process | None:
    if isinstance(process, list):
        for wf in process:
            if process_id in wf.id:
                return wf
    elif process_id in process.id:
        return process
    else:
        return None

def contains_process(
    process_id: str,
    process: Process | List[Process]
) -> bool:
    return search_process(
        process_id=process_id,
        process=process
    ) is not None

def assert_process_contained(
    process_id: str,
    process: Process | List[Process]
):
    if not contains_process(
        process_id=process_id,
        process=process
    ):
        raise ValueError(f"Process {process_id} does not exist in input CWL document, only {list(map(lambda p: p.id, process)) if isinstance(process, list) else [process.id]} available.")

def _clean_part(
    value: str,
    separator: str = '/'
) -> str:
    return value.split(separator)[-1]

def _clean_values(
    value: str | List[str],
    separator: str = '/'
) -> str | List[str]:
    if isinstance(value, list):
        return [_clean_part(value=e, separator=separator) for e in value]

    return _clean_part(value=value, separator=separator)

def remove_refs(
    process: Process | List[Process]
):
    if isinstance(process, list):
        for p in process:
            remove_refs(p)
    else:
        process.id = _clean_part(process.id, '#')

        for parameters in [ process.inputs, process.outputs ]:
            for parameter in parameters:
                parameter.id = _clean_part(parameter.id)

                if hasattr(parameter, 'outputSource'):
                    parameter.outputSource = _clean_values(parameter.outputSource, f"{process.id}/")

        for step in getattr(process, 'steps', []):
            step.id = _clean_part(step.id)

            for step_in in getattr(step, 'in_', []):
                step_in.id = _clean_part(step_in.id)
                step_in.source = _clean_values(step_in.source, f"{process.id}/")

            if getattr(step, 'out', None):
                step.out = _clean_values(step.out)

            if getattr(step, 'run', None):
                step.run = step.run[step.run.rfind('#'):]

            if getattr(step, 'scatter', None):
                step.scatter = _clean_values(step.scatter, f"{process.id}/")
        
        if process.extension_fields:
            process.extension_fields.pop(ORIGINAL_CWLVERSION)

def assert_connected_graph(
    process: Process | List[Process]
):
    index: Mapping[str, Process] = to_index(process) if isinstance(process, list) else { process.id: process }
    issues: List[str] = []

    for process in index.values():
        if any(isinstance(process, typ) for typ in get_args(Workflow)):
            for step in getattr(process, 'steps', []):
                if isinstance(step.run, str):
                    if not index.get(step.run[1:]):
                        issues .append(f"- {process.id}.steps.{step.id} = {step.run}")

    if issues:
        nl = '\n'
        raise ValueError(f"Detected unresolved links in the input $graph:\n{nl.join(issues)}")
