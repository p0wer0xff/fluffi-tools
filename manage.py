#!/usr/bin/env python3

import argparse
import logging
import os
import subprocess

import fluffi

# Constants
N_MIN = 5
N_MAX = 8
GIT_URL = "https://github.com/sears-s/fluffi"
FUZZGOAT_PATH = os.path.expanduser("~/fluffi-tools/fuzzgoat")

# Get logger
log = logging.getLogger("fluffi")


def main():
    # Setup logging
    log.setLevel(logging.DEBUG)
    logging.basicConfig(format="%(levelname)s:%(message)s")

    # Create parser
    parser = argparse.ArgumentParser()
    parser.add_argument("command", type=str, help="clone, up, down, deploy, or all")
    parser.add_argument("-n", type=int, help=f"{N_MIN}-{N_MAX} or omit for all")
    args = parser.parse_args()

    # Check host
    if args.n and (args.n < N_MIN or args.n > N_MAX):
        print("Invalid host")
        exit(1)

    # Setup up args
    with open(os.path.join(FUZZGOAT_PATH, "fuzzgoat", "rb")) as f:
        data = f.read()
    module = ("fuzzgoat", data)
    with open(os.path.join(FUZZGOAT_PATH, "seed", "rb")) as f:
        data = f.read()
    seeds = [("seed", data)]
    up_args = ["sears", "fuzzgoat/fuzzgoat", module, seeds]

    # Process command
    if args.command == "clone":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                clone(i)
        else:
            clone(args.n)
    elif args.command == "up":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.Instance(i).up(*up_args)
        else:
            fluffi.Instance(args.n).up(*up_args)
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.Instance(i).down()
        else:
            fluffi.Instance(args.n).down()
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.Instance(i).deploy()
        else:
            fluffi.Instance(args.n).deploy()
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.Instance(i).all(*up_args)
        else:
            fluffi.Instance(args.n).all(*up_args)
    else:
        print("Invalid command")
        exit(1)


def clone(n):
    location = fluffi.LOCATION_FMT.format(n)
    fluffi_path = fluffi.FLUFFI_PATH_FMT.format(n)
    print(f"Cloning {location}...")

    # Clone the repo and switch to branch
    subprocess.run(
        ["git", "clone", GIT_URL, fluffi_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "checkout", location],
        cwd=fluffi_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "lfs", "pull"],
        cwd=fluffi_path,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Prepare environment and compile dependencies
    subprocess.run(
        ["sudo", "./buildAll.sh", "PREPARE_ENV=TRUE", "WITH_DEPS=TRUE"],
        cwd=f"{fluffi_path}/build/ubuntu_based",
        check=True,
    )

    print(f"{location} cloned")


if __name__ == "__main__":
    main()
