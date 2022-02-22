#!/usr/bin/env python3

import argparse
import logging
import subprocess

import fluffi
import util

# Constants
N_MIN = 5
N_MAX = 8
SSH_SERVER_PREFIX = util.SSH_SERVER_PREFIX
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
                util.start_proxy(i)
                up(i)
                util.stop_proxy(i)
        else:
            util.start_proxy(args.n)
            up(args.n)
            util.stop_proxy(args.n)
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                util.start_proxy(i)
                down(i)
                util.stop_proxy(i)
        else:
            util.start_proxy(args.n)
            down(args.n)
            util.stop_proxy(args.n)
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                deploy(i)
        else:
            deploy(args.n)
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                util.start_proxy(i)
                down(i)
                deploy(i)
                up(i)
                util.stop_proxy(i)
        else:
            util.start_proxy(args.n)
            down(args.n)
            deploy(args.n)
            up(args.n)
            util.stop_proxy(args.n)
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


def down(n):
    log.info(f"Stopping 1021-{n}...")

    # Create session
    s = util.FaultTolerantSession(n)

    # Get fuzzjob name and ID
    fuzzjob_id, fuzzjob_name = fluffi.get_fuzzjob(s)

    # Downturn GRE
    if fuzzjob_id != -1:
        fluffi.set_gre(s, fuzzjob_name, 0, 0, 0)

    # Downturn LM
    fluffi.set_lm(s, 0)

    # Kill the leftovers
    fluffi.kill_leftover_agents(n)

    # Archive fuzzjob
    if fuzzjob_id != -1:
        fluffi.archive_fuzzjob(s, fuzzjob_id)

    # Delete log and testcase directories
    fluffi.clear_dirs(n)

    log.info(f"1021-{n} stopped")


def deploy(n):
    log.info(f"Deploying 1021-{n}...")

    # Init strings
    fluffi_path = f"{FLUFFI_PATH_PREFIX}{n}"
    ssh_server = f"{SSH_SERVER_PREFIX}{n}"

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

    log.info(f"1021-{n} deployed")


def up(n):
    log.info(f"Starting 1021-{n}...")

    # Create session
    s = util.FaultTolerantSession(n)

    # Create new fuzzjob
    _, fuzzjob_name = fluffi.new_fuzzjob(
        s,
        FUZZJOB_NAME_PREFIX,
        "fuzzgoat/fuzzgoat",
        f"{FUZZGOAT_PATH}/fuzzgoat",
        f"{FUZZGOAT_PATH}/seed",
    )

    # Upturn LM
    fluffi.set_lm(s, 1)

    # Upturn GRE
    fluffi.set_gre(s, fuzzjob_name, 2, 10, 10)

    log.info(f"1021-{n} started")


if __name__ == "__main__":
    main()
