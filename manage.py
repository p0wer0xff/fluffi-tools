#!/usr/bin/env python3

import argparse
import logging
import subprocess

import fluffi

# Constants
N_MIN = 5
N_MAX = 8
FLUFFI_PATH_FMT = "/home/sears/fluffi{}"
GIT_URL = "https://github.com/sears-s/fluffi"
FUZZGOAT_PATH = "/home/sears/fluffi-tools/fuzzgoat"
UP_ARGS = [
    "sears",
    "fuzzgoat/fuzzgoat",
    f"{FUZZGOAT_PATH}/fuzzgoat",
    f"{FUZZGOAT_PATH}/seed",
]

# Get logger
log = logging.getLogger("fluffi-tools")


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
        log.error("Invalid host")
        exit(1)

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
                fluffi.FluffiInstance(i).up(*UP_ARGS)
        else:
            fluffi.FluffiInstance(args.n).up(*UP_ARGS)
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.FluffiInstance(i).down()
        else:
            fluffi.FluffiInstance(args.n).down()
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.FluffiInstance(i).deploy()
        else:
            fluffi.FluffiInstance(args.n).deploy()
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                fluffi.FluffiInstance(i).all(*UP_ARGS)
        else:
            fluffi.FluffiInstance(args.n).all(*UP_ARGS)
    else:
        log.error("Invalid command")
        exit(1)


def clone(n):
    log.info(f"Cloning 1021-{n}...")

    # Init string
    fluffi_path = FLUFFI_PATH_FMT.format(n)

    # Clone the repo and switch to branch
    subprocess.run(
        ["git", "clone", GIT_URL, fluffi_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        ["git", "checkout", f"1021-{n}"],
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

    log.info(f"1021-{n} cloned")


if __name__ == "__main__":
    main()
