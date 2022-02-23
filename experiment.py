#!/usr/bin/env python3

import argparse
import logging
import os

import fluffi

# Constants
N_MIN = 5
N_MAX = 8
EXP_BASE_DIR = os.path.expanduser("~/fluffi-tools/experiments")
FUZZBENCH_DIR = os.path.expanduser("~/fuzzbench")

# Get logger
log = logging.getLogger("fluffi")


def main():
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("name", type=str, help="clone, up, down, deploy, or all")
    parser.add_argument("n", type=int, help=f"{N_MIN}-{N_MAX}")
    args = parser.parse_args()

    # Check host
    if args.n < N_MIN or args.n > N_MAX:
        print("Invalid host")
        exit(1)

    # Create experiment directory
    exp_dir = os.path.join(EXP_BASE_DIR, args.name)
    os.makedirs(exp_dir, exist_ok=True)

    # Setup logging
    log.setLevel(logging.INFO)
    logging.basicConfig(
        filename=os.path.join(exp_dir, "experiment.log"),
        format=f"%(asctime)s %(levelname)s:{fluffi.LOCATION_FMT.format(args.n)}:%(message)s",
        datefmt="%m/%d/%Y %H:%M:%S",
    )

    # Connect to instance and ensure nothing is running
    inst = fluffi.Instance(args.n)
    inst.down()


if __name__ == "__main__":
    main()
