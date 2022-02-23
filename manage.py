#!/usr/bin/env python3

import argparse
import logging
import subprocess

import fluffi

# Constants
N_MIN = 5
N_MAX = 8
SSH_SERVER_PREFIX = "worker"
FLUFFI_PATH_PREFIX = "/home/sears/fluffi"
GIT_URL = "https://github.com/sears-s/fluffi"
FUZZGOAT_PATH = "/home/sears/fluffi-tools/fuzzgoat"
FLUFFI_URL = "http://web.fluffi:8880"
FUZZJOB_NAME_PREFIX = "sears"

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
                up(fluffi.FluffiInstance(i))
        else:
            up(fluffi.FluffiInstance(args.n))
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                down(fluffi.FluffiInstance(i))
        else:
            down(fluffi.FluffiInstance(args.n))
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                deploy(fluffi.FluffiInstance(i))
        else:
            deploy(fluffi.FluffiInstance(args.n))
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                all(fluffi.FluffiInstance(i))
        else:
            all(fluffi.FluffiInstance(args.n))
    else:
        log.error("Invalid command")
        exit(1)


def clone(n):
    log.info(f"Cloning 1021-{n}...")

    # Init string
    fluffi_path = f"{FLUFFI_PATH_PREFIX}{n}"

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


def all(f):
    down(f)
    deploy(f)
    up(f)


def down(f):
    log.info(f"Stopping 1021-{f.n}...")

    # Get fuzzjob name and ID
    fuzzjob = f.get_fuzzjob()

    # Downturn GRE
    f.set_gre(fuzzjob, 0, 0, 0)

    # Downturn LM
    f.set_lm(0)

    # Kill the leftovers
    f.kill_leftover_agents()

    # Archive fuzzjob
    f.archive_fuzzjob(fuzzjob)

    # Delete log and testcase directories
    f.clear_dirs()

    log.info(f"1021-{f.n} stopped")


def deploy(f):
    log.info(f"Deploying 1021-{f.n}...")

    # Init strings
    fluffi_path = f"{FLUFFI_PATH_PREFIX}{f.n}"
    ssh_server = f"{SSH_SERVER_PREFIX}{f.n}"

    # Clean old build
    log.debug("Cleaning old build...")
    subprocess.run(
        ["rm", "-rf", f"{fluffi_path}/core/x86-64"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("Old build cleaned")

    # Compile new build
    log.debug("Compiling new build...")
    subprocess.run(
        ["sudo", "./buildAll.sh"],
        cwd=f"{fluffi_path}/build/ubuntu_based",
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("New build compiled")

    # Zip, SCP, and unzip
    log.debug("Transferring new build...")
    subprocess.run(
        ["zip", "-r", "fluffi.zip", "."],
        cwd=f"{fluffi_path}/core/x86-64/bin",
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "scp",
            f"{fluffi_path}/core/x86-64/bin/fluffi.zip",
            f"{ssh_server}:/home/fluffi_linux_user/fluffi/persistent/x64",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "ssh",
            f"{ssh_server}",
            "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("New build transferred")

    log.info(f"1021-{f.n} deployed")


def up(f):
    log.info(f"Starting 1021-{f.n}...")

    # Create new fuzzjob
    fuzzjob = f.new_fuzzjob(
        FUZZJOB_NAME_PREFIX,
        "fuzzgoat/fuzzgoat",
        f"{FUZZGOAT_PATH}/fuzzgoat",
        f"{FUZZGOAT_PATH}/seed",
    )

    # Upturn LM
    f.set_lm(1)

    # Upturn GRE
    f.set_gre(fuzzjob, 2, 10, 10)

    log.info(f"1021-{f.n} started")


if __name__ == "__main__":
    main()
