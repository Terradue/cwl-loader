# CLI reference

The package installs a `cwl-loader` console script that points to
`cwl_loader.cli:main`. The CLI is implemented with Click and currently exposes
one command: `bundle`.

## `bundle`

`bundle` loads a CWL document, resolves external `steps[].run` references, and
writes the resolved CWL back to a YAML file. It does not execute the workflow.

```bash
cwl-loader bundle [OPTIONS] CWL-WORKFLOW
```

### Arguments

| Argument | Description |
| --- | --- |
| `CWL-WORKFLOW` | Required. The CWL document to load. It can be a local filesystem path or a URL handled by the configured request session, such as `https://`, `s3://`, or `oci://`. |

### Options

| Option | Environment variable | Required | Description |
| --- | --- | --- | --- |
| `--output PATH` | | Yes | Destination file for the resolved CWL YAML. Parent directories are created automatically. |
| `--oci-hostname TEXT` | `OCI_HOSTNAME` | No | Hostname passed to the OCI request adapter. |
| `--oci-username TEXT` | `OCI_USERNAME` | No | Username passed to the OCI request adapter. |
| `--oci-password TEXT` | `OCI_PASSWORD` | No | Password passed to the OCI request adapter. |

Click displays option defaults and environment-variable bindings in
`cwl-loader bundle --help`.

### Examples

Bundle a local workflow:

```bash
cwl-loader bundle workflow.cwl --output build/workflow.bundle.cwl
```

Bundle a workflow from an HTTP URL:

```bash
cwl-loader bundle \
  https://example.com/workflows/workflow.cwl \
  --output build/workflow.bundle.cwl
```

Bundle a workflow that imports tools from an OCI registry:

```bash
OCI_USERNAME=my-user \
OCI_PASSWORD=my-password \
cwl-loader bundle workflow_oci.cwl --output build/workflow_oci.bundle.cwl
```

The same OCI values can also be provided as explicit options:

```bash
cwl-loader bundle workflow_oci.cwl \
  --output build/workflow_oci.bundle.cwl \
  --oci-username my-user \
  --oci-password my-password
```

## What the command does

When `bundle` runs, it creates a `requests.Session` and mounts adapters for:

- `file://` through `session_adapters.file_adapter.FileAdapter`
- `s3://` through `session_adapters.s3_adapter.S3Adapter`
- `oci://` through `session_adapters.oci_adapter.OCIAdapter`

The session also keeps the standard Requests adapters for `http://` and
`https://`. Plain local files are accepted as filesystem paths.

The command then calls `load_cwl_from_location()` with the `CWL-WORKFLOW`
argument. The loader:

- reads the document from the local path or URL;
- transparently decompresses gzip-compressed URL responses;
- loads the YAML content;
- updates the CWL model to `v1.2` when the input declares another CWL version;
- parses the document with `cwl-utils`;
- recursively imports external `steps[].run` references;
- rewrites imported process references to local `#id` references;
- removes fully qualified references;
- verifies that all step `run` links are resolvable;
- sorts process definitions by dependency order.

Finally, `bundle` creates the output directory if needed and serializes the
resolved `Process` or `$graph` back to YAML with `dump_cwl()`. Serialization uses
absolute URIs rather than relative URIs.

## Output and failures

The input file is not modified. The resolved CWL is written only to
`--output`.

The command fails if the input is not an existing local path or a supported URL,
if a remote response returns an error status, if the CWL cannot be parsed, or if
an imported `$graph` reference is ambiguous. When referencing a process inside an
external `$graph`, include the fragment, for example:

```yaml
run: oci://ghcr.io/terradue/cwl-loader/stac:latest#stac
```

If an external `$graph` contains more than one process and no fragment is
provided, the loader cannot choose an entry point and raises an error.
