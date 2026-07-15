# CWL Loader documentation

**cwl_loader** helps load CWL documents into
[cwl-utils](https://github.com/common-workflow-language/cwl-utils) object
models, normalize references, resolve imported workflow steps, and serialize the
result back to YAML.

Install it with:

```bash
pip install cwl-loader
```

The documentation is organized according to the
[Diataxis](https://diataxis.fr/) convention:

| Need | Section | Start here |
| --- | --- | --- |
| Learn by following a guided path | Tutorials | [First steps with CWL Loader](tutorials/first-steps.md) |
| Solve a specific task | How-to guides | [Load and serialize CWL](how-to/load-and-dump.md) |
| Look up the Python API | Reference | [API reference](api/latest/cwl_loader.md) |
| Understand concepts and design choices | Explanation | [The loading model](explanation/loading-model.md) |

## What CWL Loader does

CWL Loader can read CWL from local files, URLs, text streams, strings, and
Python mappings. It can update older CWL documents to `v1.2`, parse them with
`cwl-utils`, dereference external `steps[].run` imports, validate that workflow
steps point to available processes, and write the resolved document as YAML.

Use the Python API when embedding this behavior in an application.

!!! important "The bundle CLI has moved"

    The `cwl-loader bundle` command is no longer part of CWL Loader. For
    command-line bundling, use
    [Transpiler Mate](https://terradue.github.io/transpiler-mate/).
