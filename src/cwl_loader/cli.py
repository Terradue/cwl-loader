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

from . import load_cwl_from_location, dump_cwl
from cwl_utils.parser import Process
from datetime import datetime
from functools import wraps
from loguru import logger
from pathlib import Path
from session_adapters.file_adapter import FileAdapter
from session_adapters.s3_adapter import S3Adapter
from session_adapters.oci_adapter import OCIAdapter
from typing import List

import click
import requests
import time


def _track(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()

        logger.info(
            f"Started at: {datetime.fromtimestamp(start_time).isoformat(timespec='milliseconds')}"
        )

        try:
            func(*args, **kwargs)

            logger.success(
                "------------------------------------------------------------------------"
            )
            logger.success("SUCCESS")
            logger.success(
                "------------------------------------------------------------------------"
            )
        except Exception as e:
            logger.error(
                "------------------------------------------------------------------------"
            )
            logger.error("FAIL")
            logger.error(e)
            logger.error(
                "------------------------------------------------------------------------"
            )

        end_time = time.time()

        logger.info(f"Total time: {end_time - start_time:.4f} seconds")
        logger.info(
            f"Finished at: {datetime.fromtimestamp(end_time).isoformat(timespec='milliseconds')}"
        )

    return wrapper


@click.group()
def main():
    pass


@main.command(context_settings={"show_default": True})
@click.argument("cwl-workflow", required=True)
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="The output file path",
)
@click.option("--oci-hostname", envvar="OCI_HOSTNAME", show_envvar=True)
@click.option("--oci-username", envvar="OCI_USERNAME", show_envvar=True)
@click.option("--oci-password", envvar="OCI_PASSWORD", show_envvar=True)
def bundle(
    cwl_workflow: str,
    output: Path,
    oci_hostname: str | None,
    oci_username: str | None,
    oci_password: str | None,
):
    session = requests.Session()
    session.mount("file://", FileAdapter())
    session.mount("s3://", S3Adapter())
    session.mount(
        "oci://",
        OCIAdapter(hostname=oci_hostname, username=oci_username, password=oci_password),
    )

    resolved_workflow: Process | List[Process] = load_cwl_from_location(
        path=cwl_workflow, session=session
    )

    output.parent.mkdir(parents=True, exist_ok=True)

    logger.debug(f"Serializing resolved CWL to {output.absolute()}...")

    with output.open("w") as output_stream:
        dump_cwl(resolved_workflow, output_stream)

    logger.success(f"Resolved CWL successfully serialized to {output.absolute()}.")


for command in [bundle]:
    _track(command.callback)
