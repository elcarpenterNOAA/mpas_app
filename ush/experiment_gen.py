"""
Creates the experiment directory and populates it with necessary configuration and workflow files.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from shutil import copy
from subprocess import STDOUT, CalledProcessError, check_output
from typing import Optional

from uwtools.api import rocoto
from uwtools.api.config import get_yaml_config, realize
from uwtools.api.logging import use_uwtools_logger
from uwtools.config.formats.base import Config


def create_grid_files(expt_dir: Path, mesh_file_path: Path, nprocs: int) -> None:
    """
    Stage the mesh file in the experiment directory and decompose them for the current experiment.
    """
    copy(src=mesh_file_path, dst=expt_dir)
    mesh_file = expt_dir / mesh_file_path.name
    cmd = f"gpmetis -minconn -contig -niter=200 {mesh_file} {nprocs}"
    try:
        output = check_output(cmd, encoding="utf=8", shell=True, stderr=STDOUT, text=True)
    except CalledProcessError as e:
        output = e.output
        print("Error running command:")
        print(f"  {cmd}")
        for line in output.split("\n"):
            print(line)
        print(f"Failed with status: {e.returncode}")
        sys.exit(1)


def main(user_config_files: list[Path, str]) -> None:
    """
    Stage the Rocoto XML and experiment YAML in the desired experiment
    directory.
    """

    # Set up the experiment
    mpas_app = Path(os.path.dirname(__file__)).parent.absolute()
    experiment_config = get_yaml_config(Path("./default_config.yaml"))
    user_config = get_yaml_config({})
    for cfg_file in user_config_files:
        cfg = get_yaml_config(cfg_file)
        user_config.update_from(cfg)
        experiment_config.update_from(cfg)

    machine = experiment_config["user"]["platform"]
    platform_config = get_yaml_config(mpas_app / "parm" / "machines" / f"{machine}.yaml")

    # Updates based on user-selected external_models
    external_model_config = get_yaml_config(mpas_app / "ush" / "external_model_config.yaml")
    for bcs in ("ics", "lbcs"):
        model = experiment_config["user"][bcs]["external_model"]
        bcs_config = external_model_config[model][bcs]
        experiment_config.update_from(bcs_config)

    # Make sure user_config is last to override any settings from supplementals
    for supp_config in (platform_config, user_config):
        experiment_config.update_from(supp_config)

    experiment_config["user"]["mpas_app"] = mpas_app.as_posix()

    experiment_config.dereference()

    # Build the experiment directory
    experiment_path = Path(experiment_config["user"]["experiment_dir"])
    print("Experiment will be set up here: {}".format(experiment_path))
    os.makedirs(experiment_path, exist_ok=True)

    experiment_file = experiment_path / "experiment.yaml"

    # Load the workflow definition
    workflow_blocks = experiment_config["user"]["workflow_blocks"]
    workflow_blocks = [mpas_app / "parm" / "wflow" / b for b in workflow_blocks]

    workflow_config = None
    for workflow_block in workflow_blocks:
        if workflow_config is None:
            workflow_config = get_yaml_config(workflow_block)
        else:
            workflow_config.update_from(get_yaml_config(workflow_block))
    for supp_config in (experiment_config, user_config):
        workflow_config.update_from(supp_config)

    realize(
        input_config=workflow_config,
        output_file=experiment_file,
        update_config={},
    )

    # Create the workflow files
    rocoto_xml = experiment_path / "rocoto.xml"
    rocoto_valid = rocoto.realize(config=experiment_file, output_file=rocoto_xml)
    if not rocoto_valid:
        sys.exit(1)

    # Create grid files
    mesh_file_name = f"{experiment_config['user']['mesh_label']}.graph.info"
    mesh_file_path = Path(experiment_config["data"]["mesh_files"]) / mesh_file_name

    all_nprocs = []
    for sect, driver in (
        ("create_ics", "mpas_init"),
        ("create_lbcs", "mpas_init"),
        ("forecast", "mpas"),
        ("post", "mpassit"),
    ):
        if sect in experiment_config:
            resources = experiment_config[sect][driver]["execution"]["batchargs"]
            if (cores := resources.get("cores")) is None:
                cores = resources["nodes"] * resources["tasks_per_node"]
            all_nprocs.append(cores)
    for nprocs in all_nprocs:
        if not (experiment_path / f"{mesh_file_path.name}.part.{nprocs}").is_file():
            print(f"Creating grid file for {nprocs} procs")
            create_grid_files(experiment_path, mesh_file_path, nprocs)


if __name__ == "__main__":
    use_uwtools_logger()

    parser = argparse.ArgumentParser(
        description="Configure an experiment with the following input:"
    )
    parser.add_argument("user_config_files", nargs="+", help="Paths to the user config files.")

    args = parser.parse_args()
    path_list = [Path(p) for p in args.user_config_files]
    main(user_config_files=path_list)
