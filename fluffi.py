import logging
import os
import re
import subprocess
import time

import util

# Constants
PROXY_PORT_BASE = 9000
LOCATION_FMT = "1021-{}"
SSH_SERVER_FMT = "worker{}"
WORKER_NAME_FMT = "fluffi-1021-{}-Linux1"
ARCH = "x64"
FLUFFI_URL = "http://web.fluffi:8880"
FUZZJOB_ID_REGEX = r'"/projects/archive/(\d+)"'
FUZZJOB_NAME_REGEX = r"<h1>([a-zA-Z0-9]+)</h1>"
PM_URL = "http://pole.fluffi:8888/api/v2"

# Get logger
log = logging.getLogger("fluffi-tools")


class Fuzzjob:
    def __init__(self, name, id):
        self.name = name
        self.id = id


class FluffiInstance:
    def __init__(self, n):
        # Set members
        self.n = n
        self.proxy_port = PROXY_PORT_BASE + self.n
        self.location = LOCATION_FMT.format(self.n)
        self.ssh_server = SSH_SERVER_FMT.format(self.n)
        self.worker_name = WORKER_NAME_FMT.format(self.n)

        # Start proxy and initiliaze the session
        self.start_proxy()
        self.s = util.FaultTolerantSession(self.proxy_port)
        self.s.get(FLUFFI_URL)

    # Stop proxy on destruction
    def __del__(self):
        self.stop_proxy()

    ### Proxy ###

    def stop_proxy(self):
        subprocess.run(
            f"lsof -ti tcp:{self.proxy_port} | xargs kill",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug(f"Stopped proxy on port {self.proxy_port}")

    def start_proxy(self):
        self.stop_proxy()
        subprocess.run(
            f"ssh {self.ssh_server} -D {self.proxy_port} -N &",
            check=True,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        log.debug(f"Started proxy on port {self.proxy_port}")

    ### Fluffi Web ###

    def get_fuzzjob(self):
        r = self.s.get(f"{FLUFFI_URL}/projects")
        try:
            id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
        except:
            id = -1  # no current fuzzjob
            name = None
        log.debug(f"Fuzzjob ID: {id}")
        if id != -1:
            r = self.s.get(f"{FLUFFI_URL}/projects/view/{id}")
            name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
            log.debug(f"Fuzzjob name: {name}")
        return Fuzzjob(name, id)

    def new_fuzzjob(self, name_prefix, target_path, module_path, seed_path):
        log.debug(f"Creating new fuzzjob prefixed {name_prefix}...")
        while True:
            name = f"{name_prefix}{int(time.time())}"
            r = self.s.post(
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
                    ("location", (None, self.location)),
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
        return Fuzzjob(name, id)

    def archive_fuzzjob(self, fuzzjob):
        if fuzzjob.id == -1:
            return
        log.debug("Archiving fuzzjob...")
        self.s.post(f"{FLUFFI_URL}/projects/archive/{fuzzjob.id}")
        while True:
            r = self.s.get(f"{FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(util.REQ_SLEEP_TIME)
        log.debug("Fuzzjob archived")

    def set_lm(self, num):
        log.debug(f"Setting LM to {num}...")
        while True:
            r = self.s.post(
                f"{FLUFFI_URL}/systems/configureSystemInstances/{self.worker_name}",
                files={
                    "localManager_lm": (None, num),
                    "localManager_lm_arch": (None, ARCH),
                },
            )
            if "Success!" not in r.text:
                log.error(f"Error setting LM to {num}: {r.text}")
                continue
            break
        self.manage_agents()
        log.debug(f"LM set to {num}")

    def set_gre(self, fuzzjob, gen, run, eva):
        if fuzzjob.id == -1:
            return
        log.debug(f"Setting GRE to {gen}, {run}, {eva}...")
        while True:
            r = self.s.post(
                f"{FLUFFI_URL}/systems/configureFuzzjobInstances/{fuzzjob.name}",
                files={
                    f"{self.worker_name}_tg": (None, gen),
                    f"{self.worker_name}_tg_arch": (None, ARCH),
                    f"{self.worker_name}_tr": (None, run),
                    f"{self.worker_name}_tr_arch": (None, ARCH),
                    f"{self.worker_name}_te": (None, eva),
                    f"{self.worker_name}_te_arch": (None, ARCH),
                },
            )
            if "Success!" not in r.text:
                log.error(f"Error setting GRE to {gen}, {run}, {eva}: {r.text}")
                continue
            break
        self.manage_agents()
        log.debug(f"GRE set to {gen}, {run}, {eva}")

    ### Polemarch ###

    def manage_agents(self):
        s = util.FaultTolerantSession(self.proxy_port)
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

    ### SSH Cleanup ###

    def kill_leftover_agents(self):
        log.debug("Killing leftover agents...")
        subprocess.run(
            [
                "ssh",
                self.ssh_server,
                f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("Killed leftover agents")

    def clear_dirs(self):
        log.debug("Deleting log/testcase directories...")
        subprocess.run(
            [
                "ssh",
                self.ssh_server,
                "rm -rf /home/fluffi_linux_user/fluffi/persistent/x64/logs /home/fluffi_linux_user/fluffi/persistent/x64/testcaseFiles",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("Log/testcase directories deleted")
