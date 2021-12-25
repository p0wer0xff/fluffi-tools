#!/usr/bin/env python3

import re
from subprocess import DEVNULL, run
from time import sleep, time

from requests import Session

# Constants
WORKER_NUM = 5
FLUFFI_PATH = "/home/sears/fluffi"
SSH_SERVER = f"worker{WORKER_NUM}"
WORKER_NAME = f"fluffi-1021-{WORKER_NUM}-Linux1"
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


def stop_proxy():
    run(
        f"lsof -ti tcp:{PROXY_PORT} | xargs kill",
        shell=True,
        stdout=DEVNULL,
        stderr=DEVNULL,
    )
    print("Stopped proxy")


def manage_agents():
    s = Session()
    s.proxies.update(PROXIES)
    s.auth = ("admin", "admin")
    print("Starting manage agents task...")
    r = s.post(PM_URL + "/project/1/periodic_task/3/execute/")
    history_id = r.json()["history_id"]
    sleep(0.5)
    while True:
        try:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
        except:
            sleep(0.5)
            continue
        if r.json()["status"] == "OK":
            break
        sleep(0.5)
    print("Manage agents success")


# Start proxy
stop_proxy()
run(f"ssh {SSH_SERVER} -D {PROXY_PORT} -N &", check=True, shell=True)
sleep(0.5)
print("Started proxy")

# Create session
s = Session()
s.proxies.update(PROXIES)

# Get fuzzjob ID
r = s.get(FLUFFI_URL + "/projects")
fuzzjob_id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
print(f"Fuzzjob ID: {fuzzjob_id}")

# Get fuzzjob name
r = s.get(f"{FLUFFI_URL}/projects/view/{fuzzjob_id}")
fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
print(f"Fuzzjob name: {fuzzjob_name}")

# Downturn GRE
print("Downturning GRE...")
r = s.post(
    f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
    files={
        f"{WORKER_NAME}_tg": (None, 0),
        f"{WORKER_NAME}_tg_arch": (None, ARCH),
        f"{WORKER_NAME}_tr": (None, 0),
        f"{WORKER_NAME}_tr_arch": (None, ARCH),
        f"{WORKER_NAME}_te": (None, 0),
        f"{WORKER_NAME}_te_arch": (None, ARCH),
    },
)
if "Success!" not in r.text:
    print("Error downturning GRE")
    stop_proxy()
    exit(1)
manage_agents()
print("GRE downturned")

# Downturn LM
print("Downturning LM...")
r = s.post(
    f"{FLUFFI_URL}/systems/configureSystemInstances/{WORKER_NAME}",
    files={
        "localManager_lm": (None, 0),
        "localManager_lm_arch": (None, ARCH),
    },
)
if "Success!" not in r.text:
    print("Error downturning LM")
    stop_proxy()
    exit(1)
manage_agents()
print("LM downturned")

# Kill the leftovers
print("Killing leftovers...")
run(
    [
        "ssh",
        SSH_SERVER,
        f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
    ]
)
print("Killed leftovers")

# Archive fuzzjob
print("Archiving fuzzjob...")
s.post(f"{FLUFFI_URL}/projects/archive/{fuzzjob_id}")
while True:
    r = s.get(FLUFFI_URL + "/progressArchiveFuzzjob")
    if "5/5" in r.text:
        break
    sleep(0.25)
print("Archive success")

# Clean old build
print("Cleaning old build...")
run(["rm", "-rf", f"{FLUFFI_PATH}/core/x86-64"], check=True)
print("Old build cleaned")

# Compile new build
print("Compiling new build...")
run(
    ["sudo", "./buildAll.sh"],
    cwd=f"{FLUFFI_PATH}/build/ubuntu_based",
    check=True,
    stdout=DEVNULL,
    stderr=DEVNULL,
)
print("New build compiled")

# Zip, SCP, and unzip
print("Transferring new build...")
run(
    ["zip", "-r", "fluffi.zip", "."],
    cwd=f"{FLUFFI_PATH}/core/x86-64/bin",
    check=True,
    stdout=DEVNULL,
    stderr=DEVNULL,
)
run(
    [
        "scp",
        f"{FLUFFI_PATH}/core/x86-64/bin/fluffi.zip",
        f"{SSH_SERVER}:/home/fluffi_linux_user/fluffi/persistent/x64",
    ],
    check=True,
    stdout=DEVNULL,
    stderr=DEVNULL,
)
run(
    [
        "ssh",
        SSH_SERVER,
        "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
    ],
    check=True,
    stdout=DEVNULL,
    stderr=DEVNULL,
)
print("New build transferred")

# Create new fuzzjob
print("Creating new fuzzjob...")
r = s.post(
    FLUFFI_URL + "/projects/createProject",
    files=[
        ("name", (None, FUZZJOB_NAME_PREFIX + str(int(time())))),
        ("subtype", (None, "X64_Lin_DynRioSingle")),
        ("generatorTypes", (None, 100)),  # RadamsaMutator
        ("generatorTypes", (None, 0)),  # AFLMutator
        ("generatorTypes", (None, 0)),  # CaRRoTMutator
        ("generatorTypes", (None, 0)),  # HonggfuzzMutator
        ("generatorTypes", (None, 0)),  # OedipusMutator
        ("generatorTypes", (None, 0)),  # ExternalMutator
        ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
        ("location", (None, f"1021-{WORKER_NUM}")),
        (
            "targetCMDLine",
            (None, "/home/fluffi_linux_user/fluffi/persistent/SUT/fuzzgoat"),
        ),
        ("option_module", (None, "hangeTimeout")),
        ("option_module_value", (None, 5000)),
        (
            "targetModulesOnCreate",
            ("fuzzgoat", open(FLUFFI_PATH + "/fuzzgoat/fuzzgoat", "rb")),
        ),
        ("targetFile", (None, "")),
        ("filename", ("seed", open(FLUFFI_PATH + "/fuzzgoat/seed", "rb"))),
        ("basicBlockFile", (None, "")),
    ],
)
if "Success" not in r.text:
    print("Error creating new fuzzjob")
    stop_proxy()
    exit(1)
print("Fuzzjob created")

# Get fuzzjob ID
fuzzjob_id = int(r.url.split("/view/")[1])
print(f"Fuzzjob ID: {fuzzjob_id}")

# Get fuzzjob name
fuzzjob_name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
print(f"Fuzzjob name: {fuzzjob_name}")

# Upturn LM
print("Upturning LM...")
r = s.post(
    f"{FLUFFI_URL}/systems/configureSystemInstances/{WORKER_NAME}",
    files={
        "localManager_lm": (None, 1),
        "localManager_lm_arch": (None, ARCH),
    },
)
if "Success!" not in r.text:
    print("Error upturning LM")
    stop_proxy()
    exit(1)
manage_agents()
print("LM upturned")

# Upturn GRE
print("Upturning GRE...")
r = s.post(
    f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob_name}",
    files={
        f"{WORKER_NAME}_tg": (None, 2),
        f"{WORKER_NAME}_tg_arch": (None, ARCH),
        f"{WORKER_NAME}_tr": (None, 10),
        f"{WORKER_NAME}_tr_arch": (None, ARCH),
        f"{WORKER_NAME}_te": (None, 10),
        f"{WORKER_NAME}_te_arch": (None, ARCH),
    },
)
if "Success!" not in r.text:
    print("Error upturning GRE")
    stop_proxy()
    exit(1)
manage_agents()
print("GRE upturned")

# Stop proxy
stop_proxy()
