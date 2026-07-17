# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This changelog was reconstructed from the git history and release tags available
in this repository. The `0.16.0` entry covers the project history up to the first
local release tag.

## [Unreleased]

### Added

### Changed

### Deprecated

### Removed

### Fixed

### Security

## [0.22.0] - 2026-07-17

### Fixed

- Prevent inconsistent CWLs loading by detecting multiple `Workflow`/`CommandLineTool` from multiple imported sources have the same `id`. 

## [0.21.0] - 2026-07-15

### Changed

- Move the `bundle` CLI tool to
  [Transpiler Mate](https://terradue.github.io/transpiler-mate/). CWL Loader
  continues to provide its Python loading and serialization APIs.

## [0.20.0] - 2026-06-15

### Changed

- click dependency upgraded to v8.4.1

## [0.19.0] - 2026-05-13

### Fixed

- Preserve document-level metadata from `$graph` CWL documents when loading and
  dumping, including custom metadata fields and namespace declarations.
- Keep single-item `$graph` documents wrapped in their `$graph` envelope when
  dumping after load.

## [0.18.0] - 2026-05-13

### Added

- Add PyPI version and supported Python version badges to the README.

### Changed

- Improve external CWL import resolution for referenced `$graph` fragments and
  imported workflow dependencies.

### Fixed

- Apply the CLI tracking wrapper to the registered `bundle` command callback.

## [0.17.0] - 2026-05-05

### Added

- Add the `cwl-loader bundle` CLI command to resolve a CWL workflow and write the
  bundled result to a file.
- Add CLI support for `file://`, `s3://`, and `oci://` imports, with OCI
  credentials accepted through options or environment variables.
- Add documentation for loading and dumping CWL documents, bundling workflows,
  the CLI reference, tutorials, and the loading model.
- Add sample CWL test data and a Taskfile task for publishing CommandLineTool
  CWL files as OCI artifacts to GHCR.

### Changed

- Replace local quality Taskfile tasks with the shared remote
  `taskfile-utils` quality include.
- Update GitHub Actions dependencies and package dependencies required by the
  new CLI workflow.

### Fixed

- Correct project license metadata to `Apache-2.0`.
- Fix the OCI artifact upload Taskfile task.

## [0.16.0] - 2026-04-08

### Added

- Add the initial `cwl-loader` package APIs for loading CWL documents from YAML
  mappings, streams, strings, local files, and remote URLs into `cwl-utils`
  parser models.
- Add CWL serialization with `dump_cwl`.
- Add CWL version normalization to target CWL `v1.2` through `cwltool.update`.
- Add external `steps[].run` dereferencing and reference cleanup for process IDs,
  step inputs, step outputs, scatter sources, and workflow outputs.
- Add dependency-aware sorting for top-level `$graph` processes and workflow
  steps.
- Add validation for connected `$graph` references with errors for unresolved
  `steps[].run` links.
- Add project documentation, MkDocs configuration, example notebook content,
  CI/package publishing workflows, and unit tests.

### Changed

- Update core dependencies and release automation in preparation for package
  publishing.
- Relicense project files and package metadata under Apache License 2.0.

### Fixed

- Support loading from plain dictionaries as well as `CommentedMap` instances.
- Handle `outputSource`, `step.in.source`, and `step.out` values represented as
  either strings or lists.
- Handle null `step.in.source` values during reference cleanup.
- Avoid false positives while checking `in` predicates during reference cleanup.
- Fix workflow separation when a step name matches the main workflow name.
- Remove `ORIGINAL_CWLVERSION` extension fields during cleanup.
- Fix the `dump_cwl` method signature and documentation/notebook build issues.
- Correct project naming, license content, formatting, tests, and CI setup.

[Unreleased]: https://github.com/Terradue/cwl-loader/compare/v0.21.0...HEAD
[0.22.0]: https://github.com/Terradue/cwl-loader/compare/v0.21.0...v0.22.0
[0.21.0]: https://github.com/Terradue/cwl-loader/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/Terradue/cwl-loader/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/Terradue/cwl-loader/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/Terradue/cwl-loader/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/Terradue/cwl-loader/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/Terradue/cwl-loader/releases/tag/v0.16.0
