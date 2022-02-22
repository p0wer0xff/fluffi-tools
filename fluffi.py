import logging
import os
import re
import subprocess
import time

import util

# Constants
ARCH = "x64"
FLUFFI_URL = "http://web.fluffi:8880"
FUZZJOB_ID_REGEX = r'"/projects/archive/(\d+)"'
FUZZJOB_NAME_REGEX = r"<h1>([a-zA-Z0-9]+)</h1>"
WORKER_NAME_FMT = "fluffi-1021-{}-Linux1"
SSH_SERVER_FMT = "worker{}"
PM_URL = "http://pole.fluffi:8888/api/v2"

# Get logger
log = logging.getLogger("fluffi-tools")

# Get fuzzjob name and ID
def get_fuzzjob(s):
    r = s.get(f"{FLUFFI_URL}/projects")
    try:
        id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
    except:
        id = -1  # no current fuzzjob
        name = None
    log.debug(f"Fuzzjob ID: {id}")
    if id != -1:
        r = s.get(f"{FLUFFI_URL}/projects/view/{id}")
        name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
        log.debug(f"Fuzzjob name: {name}")
    return id, name


# Creates a new fuzzjob, returns ID and name
def new_fuzzjob(s, name_prefix, target_path, module_path, seed_path):
    log.debug(f"Creating new fuzzjob prefixed {name_prefix}...")
    while True:
        name = f"{name_prefix}{int(time.time())}"
        r = s.post(
            f"{FLUFFI_URL}/projects/createProject",
            files=[
                ("name", (None, name)),
                ("subtype", (None, "X64_Lin_DynRioSingle")),
                ("generatorTypes", (None, 100)),  # RadamsaMutator
                ("generatorTypes", (None, 0)),  # AFLMutator
                ("generatorTypes", (None, 0)),  # CaRRoTMutator
                ("generatorTypes", (None, 0)),  # HonggfuzzMutator
                ("generatorTypes", (None, 0)),  # OedipusMutator
                ("generatorTypes", (None, 0)),  # ExternalMutator
                ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
                ("location", (None, f"1021-{s.n}")),
                (
                    "targetCMDLine",
                    (
                        None,
                        os.path.join(
                            "/home/fluffi_linux_user/fluffi/persistent/SUT/",
                            target_path,
                        ),
                    ),
                ),
                ("option_module", (None, "hangeTimeout")),
                ("option_module_value", (None, 5000)),
                (
                    "targetModulesOnCreate",
                    ("fuzzgoat", open(module_path, "rb")),
                ),
                ("targetFile", (None, "")),
                ("filename", ("seed", open(seed_path, "rb"))),
                ("basicBlockFile", (None, "")),
            ],
        )
        if "Success" not in r.text:
            log.error(f"Error creating new fuzzjob named {name}: {r.text}")
            continue
        break
    id = int(r.url.split("/view/")[1])
    log.debug(f"Fuzzjob named {name} created with ID {id}")
    return id, name


# Removes a fuzzjob
def archive_fuzzjob(s, id):
    log.debug("Archiving fuzzjob...")
    s.post(f"{FLUFFI_URL}/projects/archive/{id}")
    while True:
        r = s.get(f"{FLUFFI_URL}/progressArchiveFuzzjob")
        if "5/5" in r.text:
            break
        time.sleep(util.REQ_SLEEP_TIME)
    log.debug("Fuzzjob archived")


def set_lm(s, num):
    log.debug(f"Setting LM to {num}...")
    worker_name = WORKER_NAME_FMT.format(s.n)
    while True:
        r = s.post(
            f"{FLUFFI_URL}/systems/configureSystemInstances/{worker_name}",
            files={
                "localManager_lm": (None, num),
                "localManager_lm_arch": (None, ARCH),
            },
        )
        if "Success!" not in r.text:
            log.error(f"Error setting LM to {num}: {r.text}")
            continue
        break
    manage_agents(s.n)
    log.debug(f"LM set to {num}")


# Set number of generators, runner, and evaluators
def set_gre(s, name, gen, run, eva):
    log.debug(f"Setting GRE to {gen}, {run}, {eva}...")
    worker_name = WORKER_NAME_FMT.format(s.n)
    while True:
        r = s.post(
            f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{name}",
            files={
                f"{worker_name}_tg": (None, gen),
                f"{worker_name}_tg_arch": (None, ARCH),
                f"{worker_name}_tr": (None, run),
                f"{worker_name}_tr_arch": (None, ARCH),
                f"{worker_name}_te": (None, eva),
                f"{worker_name}_te_arch": (None, ARCH),
            },
        )
        if "Success!" not in r.text:
            log.error(f"Error setting GRE to {gen}, {run}, {eva}: {r.text}")
            continue
        break
    manage_agents(s.n)
    log.debug(f"GRE set to {gen}, {run}, {eva}")


# Kill remaining worker agents via SSH
def kill_leftover_agents(n):
    log.debug("Killing leftover agents...")
    ssh_server = SSH_SERVER_FMT.format(n)
    subprocess.run(
        [
            "ssh",
            f"{ssh_server}{n}",
            f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug("Killed leftover agents")


# Delete log and testcase directories via SSH
def clear_dirs(n):
    log.debug("Deleting log/testcase directories...")
    ssh_server = SSH_SERVER_FMT.format(n)
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


# Start manage agents task in ansible
def manage_agents(n):
    s = util.FaultTolerantSession(n)
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
