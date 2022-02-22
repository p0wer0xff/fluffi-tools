#!/usr/bin/env python3

import argparse
import logging
import re
import subprocess
import time

import util

# Constants
N_MIN = 5
N_MAX = 8
SSH_SERVER_PREFIX = "worker"
WORKER_NAME_PREFIX = "fluffi-1021-"
WORKER_NAME_SUFFIX = "-Linux1"
FLUFFI_PATH_PREFIX = "/home/sears/fluffi"
GIT_URL = "https://github.com/sears-s/fluffi"
FUZZGOAT_PATH = "/home/sears/fluffi-tools/fuzzgoat"
ARCH = "x64"
PROXY_PORT = 8888
PROXIES = {
    "http": f"socks5h://127.0.0.1:{PROXY_PORT}",
    "https": f"socks5h://127.0.0.1:{PROXY_PORT}",
}
FLUFFI_URL = "http://web.fluffi:8880"
PM_URL = "http://pole.fluffi:8888/api/v2"
FUZZJOB_ID_REGEX = r'"/projects/archive/(\d+)"'
FUZZJOB_NAME_REGEX = r"<h1>([a-zA-Z0-9]+)</h1>"
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
                start_proxy(i)
                up(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            up(args.n)
            stop_proxy()
    elif args.command == "down":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                start_proxy(i)
                down(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            down(args.n)
            stop_proxy()
    elif args.command == "deploy":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                deploy(i)
        else:
            deploy(args.n)
    elif args.command == "all":
        if args.n is None:
            for i in range(N_MIN, N_MAX + 1):
                start_proxy(i)
                down(i)
                deploy(i)
                up(i)
                stop_proxy()
        else:
            start_proxy(args.n)
            down(args.n)
            deploy(args.n)
            up(args.n)
            stop_proxy()
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


def stop_proxy():
    subprocess.run(
        f"lsof -ti tcp:{PROXY_PORT} | xargs kill",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("Stopped proxy")


def start_proxy(n):
    stop_proxy()
    subprocess.run(
        f"ssh {SSH_SERVER_PREFIX}{n} -D {PROXY_PORT} -N &",
        check=True,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    log.debug("Started proxy")


def manage_agents():
    s = util.FaultTolerantSession()
    s.proxies.update(PROXIES)
    s.auth = ("admin", "admin")
    log.debug("Starting manage agents task...")
    r = s.post(f"{PM_URL}/project/1/periodic_task/3/execute/")
    history_id = r.json()["history_id"]
    time.sleep(1)
    while True:
        r = s.get(f"{PM_URL}/project/1/history/{history_id}")
        if r.json()["status"] == "OK":
            break
        time.sleep(util.REQ_SLEEP_TIME)
    log.debug("Manage agents success")


def down(n):
    log.info(f"Stopping 1021-{n}...")

    # Init strings
    worker_name = f"{WORKER_NAME_PREFIX}{n}{WORKER_NAME_SUFFIX}"
    ssh_server = f"{SSH_SERVER_PREFIX}{n}"

    # Create session
    s = util.FaultTolerantSession()
    s.proxies.update(PROXIES)

    # Get fuzzjob ID
    r = s.get(f"{FLUFFI_URL}/projects")
    try:
        fuzzjob_id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
    except:
        fuzzjob_id = -1  # no current fuzzjob
    log.debug(f"Fuzzjob ID: {fuzzjob_id}")

    # Get fuzzjob name
    if fuzzjob_id != -1:
        r = s.get(f"{FLUFFI_URL}/projects/view/{fuzzjob_id}")
        fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
        log.debug(f"Fuzzjob name: {fuzzjob_name}")

    # Downturn GRE
    if fuzzjob_id != -1:
        log.debug("Downturning GRE...")
        r = s.post(
            f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
            files={
                f"{worker_name}_tg": (None, 0),
                f"{worker_name}_tg_arch": (None, ARCH),
                f"{worker_name}_tr": (None, 0),
                f"{worker_name}_tr_arch": (None, ARCH),
                f"{worker_name}_te": (None, 0),
                f"{worker_name}_te_arch": (None, ARCH),
            },
        )
        if "Success!" not in r.text:
            log.error(f"Error downturning GRE: {r.text}")
            stop_proxy()
            exit(1)
        manage_agents()
        log.debug("GRE downturned")

    # Downturn LM
    log.debug("Downturning LM...")
    r = s.post(
        f"{FLUFFI_URL}/systems/configureSystemInstances/{worker_name}",
        files={
            "localManager_lm": (None, 0),
            "localManager_lm_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        log.error(f"Error downturning LM: {r.text}")
        stop_proxy()
        exit(1)
    manage_agents()
    log.debug("LM downturned")

    # Kill the leftovers
    log.debug("Killing leftovers...")
    subprocess.run(
        [
            "ssh",
            f"{SSH_SERVER_PREFIX}{n}",
            f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("Killed leftovers")

    # Archive fuzzjob
    if fuzzjob_id != -1:
        log.debug("Archiving fuzzjob...")
        s.post(f"{FLUFFI_URL}/projects/archive/{fuzzjob_id}")
        while True:
            r = s.get(f"{FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(util.REQ_SLEEP_TIME)
        log.debug("Archive success")

    # Delete log and testcase directories
    log.debug("Deleting log/testcase directories...")
    subprocess.run(
        [
            "ssh",
            f"{ssh_server}",
            "rm -rf /home/fluffi_linux_user/fluffi/persistent/x64/logs /home/fluffi_linux_user/fluffi/persistent/x64/testcaseFiles",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("Log/testcase directories deleted")

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

    # Init string
    worker_name = f"{WORKER_NAME_PREFIX}{n}{WORKER_NAME_SUFFIX}"

    # Create session
    s = util.FaultTolerantSession()
    s.proxies.update(PROXIES)

    # Create new fuzzjob
    log.debug("Creating new fuzzjob...")
    r = s.post(
        f"{FLUFFI_URL}/projects/createProject",
        files=[
            ("name", (None, f"{FUZZJOB_NAME_PREFIX}{int(time.time())}")),
            ("subtype", (None, "X64_Lin_DynRioSingle")),
            ("generatorTypes", (None, 100)),  # RadamsaMutator
            ("generatorTypes", (None, 0)),  # AFLMutator
            ("generatorTypes", (None, 0)),  # CaRRoTMutator
            ("generatorTypes", (None, 0)),  # HonggfuzzMutator
            ("generatorTypes", (None, 0)),  # OedipusMutator
            ("generatorTypes", (None, 0)),  # ExternalMutator
            ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
            ("location", (None, f"1021-{n}")),
            (
                "targetCMDLine",
                (
                    None,
                    "/home/fluffi_linux_user/fluffi/persistent/SUT/fuzzgoat/fuzzgoat",
                ),
            ),
            ("option_module", (None, "hangeTimeout")),
            ("option_module_value", (None, 5000)),
            (
                "targetModulesOnCreate",
                ("fuzzgoat", open(f"{FUZZGOAT_PATH}/fuzzgoat", "rb")),
            ),
            ("targetFile", (None, "")),
            ("filename", ("seed", open(f"{FUZZGOAT_PATH}/seed", "rb"))),
            ("basicBlockFile", (None, "")),
        ],
    )
    if "Success" not in r.text:
        log.error(f"Error creating new fuzzjob: {r.text}")
        stop_proxy()
        exit(1)
    log.debug("Fuzzjob created")

    # Get fuzzjob ID
    fuzzjob_id = int(r.url.split("/view/")[1])
    log.debug(f"Fuzzjob ID: {fuzzjob_id}")

    # Get fuzzjob name
    fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
    log.debug(f"Fuzzjob name: {fuzzjob_name}")

    # Upturn LM
    log.debug("Upturning LM...")
    r = s.post(
        f"{FLUFFI_URL}/systems/configureSystemInstances/{worker_name}",
        files={
            "localManager_lm": (None, 1),
            "localManager_lm_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        log.error(f"Error upturning LM: {r.text}")
        stop_proxy()
        exit(1)
    manage_agents()
    log.debug("LM upturned")

    # Upturn GRE
    log.debug("Upturning GRE...")
    r = s.post(
        f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
        files={
            f"{worker_name}_tg": (None, 2),
            f"{worker_name}_tg_arch": (None, ARCH),
            f"{worker_name}_tr": (None, 10),
            f"{worker_name}_tr_arch": (None, ARCH),
            f"{worker_name}_te": (None, 10),
            f"{worker_name}_te_arch": (None, ARCH),
        },
    )
    if "Success!" not in r.text:
        log.error(f"Error upturning GRE: {r.text}")
        stop_proxy()
        exit(1)
    manage_agents()
    log.debug("GRE upturned")

    log.info(f"1021-{n} started")


if __name__ == "__main__":
    main()
