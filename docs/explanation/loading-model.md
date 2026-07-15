# The loading model

CWL workflows often span more than one document. A workflow step can point to a
tool or workflow stored in another file, an HTTP URL, an S3 object, or an OCI
artifact. CWL Loader provides one path for turning that distributed input into a
resolved `cwl-utils` object model.

## Loading is separate from execution

CWL Loader does not run workflows. It reads CWL documents, parses them, resolves
references, and writes CWL back to YAML. A workflow runner is still responsible
for executing the resulting workflow.

This separation is useful when you need to inspect, normalize, validate, or
resolve CWL before passing it to another system.

## What resolution means

When the loader encounters a workflow step, it checks the step `run` value. If
the value points outside the current document, the loader imports that referenced
CWL document with the same request session.

After import, the loader rewrites external process references to local fragment
references such as `#stac`. This produces a document graph that can be serialized
as one resolved CWL document.

The loader then removes fully qualified references, verifies that step `run`
links point to available process IDs, and sorts process definitions by
dependency order.

## Source handling

`load_cwl_from_location()` accepts local filesystem paths and URLs supported by
the configured `requests.Session`.

Applications can configure the request session with adapters for additional URL
schemes. HTTP and HTTPS use the default Requests adapters. URL responses that
start with the gzip magic bytes are decompressed before YAML parsing.

## CWL version normalization

The loader targets CWL `v1.2`. If a document declares another CWL version, the
loader asks `cwltool` to update the raw model before parsing it with
`cwl-utils`.

This makes older documents easier to consume through one object model, but it
also means the serialized output can differ from the input even when the input
was already valid CWL.

## Python API and command-line bundling

Use the Python API when a program needs access to the parsed `Process` objects or
when you need to supply a custom request session.

The former `cwl-loader bundle` command has moved to
[Transpiler Mate](https://terradue.github.io/transpiler-mate/). Use Transpiler
Mate when the desired result is a resolved YAML file produced from the command
line.
