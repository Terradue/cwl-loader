"""
The CWL Loader Python library is a helper library to simplify the parse and serialize operations of CWL documents to and from [cwl-utils](https://github.com/common-workflow-language/cwl-utils) object models.

CWL Loader (c) 2025

CWL Loader is licensed under
Creative Commons Attribution-ShareAlike 4.0 International.

You should have received a copy of the license along with this work.
If not, see <https://creativecommons.org/licenses/by-sa/4.0/>.
"""

from cwl_utils.parser import (
    Process
)
from cwltool.update import ORIGINAL_CWLVERSION
from typing import (
    List,
    Mapping,
    TypeVar
)

T = TypeVar('T')

def to_dict(
    collection: List[T]
) -> Mapping[str, T]:
    result: Mapping[str, T] = {}

    for item in collection:
        id = getattr(item, 'id', None)
        if id:
            result[id] = item

    return result

def search_workflow(
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

def contains_workflow(
    process_id: str,
    process: Process | List[Process]
) -> bool:
    return search_workflow(
        process_id=process_id,
        process=process
    ) is not None

def _clean_part(
    value: str,
    separator: str = '/'
) -> str:
    return value.split(separator)[-1]

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
                    for i, output_source in enumerate(parameter.outputSource):
                        parameter.outputSource[i] = _clean_part(output_source, f"{process.id}/")

        for step in getattr(process, 'steps', []):
            step.id = _clean_part(step.id)

            for step_in in getattr(step, 'in_', []):
                step_in.id = _clean_part(step_in.id)
                step_in.source = _clean_part(step_in.source, f"{process.id}/")

            if getattr(step, 'out', None):
                if isinstance(step.out, list):
                    step.out = [_clean_part(step_out) for step_out in step.out]
                else:
                    step.out = _clean_part(step)

            if getattr(step, 'run', None):
                step.run = step.run[step.run.rfind('#'):]

            if getattr(step, 'scatter', None):
                if isinstance(step.scatter, list):
                    step.scatter = [_clean_part(scatter, f"{process.id}/") for scatter in step.scatter]
                else:
                    step.scatter = _clean_part(step.scatter, f"{process.id}/")
        
        if process.extension_fields:
            process.extension_fields.pop(ORIGINAL_CWLVERSION)
