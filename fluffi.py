import logging
import os
import re
import subprocess
import time

import requests

# Constants
FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25
PROXY_PORT_BASE = 9000
FLUFFI_PATH_FMT = "/home/sears/fluffi{}"
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


class FaultTolerantSession(requests.Session):
    def __init__(self, n, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.location = LOCATION_FMT.format(n)

        # Use SSH proxy server
        proxy_port = PROXY_PORT_BASE + n
        proxies = {
            "http": f"socks5h://127.0.0.1:{proxy_port}",
            "https": f"socks5h://127.0.0.1:{proxy_port}",
        }
        self.proxies.update(proxies)

    # Add location to log messages
    def __log(self, msg):
        return f"{self.location}: {msg}"

    def warn(self, msg):
        return log.warn(self.__log(msg))

    # Perform fault tolerant requests
    def request(self, *args, **kwargs):
        while True:
            try:
                r = super().request(*args, **kwargs)
            except Exception as e:
                self.warn(f"Request exception: {e}")
                time.sleep(REQ_SLEEP_TIME)
                continue
            if FLUFFI_DB_ERROR_STR in r.text:
                self.warn("Fluffi web app DB connection failed")
            elif not r.ok:
                self.warn(f"Request got status code {r.status_code}")
            else:
                return r
            time.sleep(REQ_SLEEP_TIME)


class Fuzzjob:
    def __init__(self, name, id):
        self.name = name
        self.id = id


class FluffiInstance:
    def __init__(self, n):
        # Set members
        self.n = n
        self.proxy_port = PROXY_PORT_BASE + self.n
        self.fluffi_path = FLUFFI_PATH_FMT.format(self.n)
        self.location = LOCATION_FMT.format(self.n)
        self.ssh_server = SSH_SERVER_FMT.format(self.n)
        self.worker_name = WORKER_NAME_FMT.format(self.n)

        # Start proxy and initialize the session
        self.start_proxy()
        self.s = FaultTolerantSession(self.n)
        self.s.get(FLUFFI_URL)

    # Stop proxy on destruction
    def __del__(self):
        self.stop_proxy()

    # Add location to log messages
    def __log(self, msg):
        return f"{self.location}: {msg}"

    def debug(self, msg):
        return log.debug(self.__log(msg))

    def info(self, msg):
        return log.info(self.__log(msg))

    def error(self, msg):
        return log.error(self.__log(msg))

    ### High Level Functionality ###

    def deploy(self, clean=True):
        self.info("Deploying...")

        # Clean old build
        if clean:
            self.debug("Cleaning old build...")
            subprocess.run(
                ["rm", "-rf", f"{self.fluffi_path}/core/x86-64"],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.debug("Old build cleaned")

        # Compile new build
        self.debug("Compiling new build...")
        subprocess.run(
            ["sudo", "./buildAll.sh"],
            cwd=f"{self.fluffi_path}/build/ubuntu_based",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.debug("New build compiled")

        # Zip, SCP, and unzip
        self.debug("Transferring new build...")
        subprocess.run(
            ["zip", "-r", "fluffi.zip", "."],
            cwd=f"{self.fluffi_path}/core/x86-64/bin",
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "scp",
                f"{self.fluffi_path}/core/x86-64/bin/fluffi.zip",
                f"{self.ssh_server}:/home/fluffi_linux_user/fluffi/persistent/{ARCH}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            [
                "ssh",
                f"{self.ssh_server}",
                "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.debug("New build transferred")

        self.info("Deployed")

    def up(self, fuzzjob_name_prefix, target_path, module_path, seed_path):
        self.info("Starting...")
        fuzzjob = self.new_fuzzjob(
            fuzzjob_name_prefix,
            target_path,
            module_path,
            seed_path,
        )
        self.set_lm(1)
        self.set_gre(fuzzjob, 2, 10, 10)
        self.info("Started")

    def down(self):
        self.info("Stopping...")
        fuzzjob = self.get_fuzzjob()
        self.set_gre(fuzzjob, 0, 0, 0)
        self.set_lm(0)
        self.kill_leftover_agents()
        self.archive_fuzzjob(fuzzjob)
        self.clear_dirs()
        self.info("Stopped")

    def all(self, fuzzjob_name_prefix, target_path, module_path, seed_path):
        self.down()
        self.deploy()
        self.up(fuzzjob_name_prefix, target_path, module_path, seed_path)

    ### Proxy ###

    def stop_proxy(self):
        subprocess.run(
            f"lsof -ti tcp:{self.proxy_port} | xargs kill",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.debug(f"Stopped proxy on port {self.proxy_port}")

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
        self.debug(f"Started proxy on port {self.proxy_port}")

    ### Fluffi Web ###

    def get_fuzzjob(self):
        r = self.s.get(f"{FLUFFI_URL}/projects")
        try:
            id = int(re.search(FUZZJOB_ID_REGEX, r.text).group(1))
        except:
            id = -1  # no current fuzzjob
            name = None
        self.debug(f"Fuzzjob ID: {id}")
        if id != -1:
            r = self.s.get(f"{FLUFFI_URL}/projects/view/{id}")
            name = re.search(FUZZJOB_NAME_REGEX, r.text).group(1)
            self.debug(f"Fuzzjob name: {name}")
        return Fuzzjob(name, id)

    def new_fuzzjob(self, name_prefix, target_path, module_path, seed_path):
        self.debug(f"Creating new fuzzjob prefixed {name_prefix}...")
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
                self.error(f"Error creating new fuzzjob named {name}: {r.text}")
                continue
            break
        id = int(r.url.split("/view/")[1])
        self.debug(f"Fuzzjob named {name} created with ID {id}")
        return Fuzzjob(name, id)

    def archive_fuzzjob(self, fuzzjob):
        if fuzzjob.id == -1:
            return
        self.debug("Archiving fuzzjob...")
        self.s.post(f"{FLUFFI_URL}/projects/archive/{fuzzjob.id}")
        while True:
            r = self.s.get(f"{FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(REQ_SLEEP_TIME)
        self.debug("Fuzzjob archived")

    def set_lm(self, num):
        self.debug(f"Setting LM to {num}...")
        while True:
            r = self.s.post(
                f"{FLUFFI_URL}/systems/configureSystemInstances/{self.worker_name}",
                files={
                    "localManager_lm": (None, num),
                    "localManager_lm_arch": (None, ARCH),
                },
            )
            if "Success!" not in r.text:
                self.error(f"Error setting LM to {num}: {r.text}")
                continue
            break
        self.manage_agents()
        self.debug(f"LM set to {num}")

    def set_gre(self, fuzzjob, gen, run, eva):
        if fuzzjob.id == -1:
            return
        self.debug(f"Setting GRE to {gen}, {run}, {eva}...")
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
                self.error(f"Error setting GRE to {gen}, {run}, {eva}: {r.text}")
                continue
            break
        self.manage_agents()
        self.debug(f"GRE set to {gen}, {run}, {eva}")

    ### Polemarch ###

    def manage_agents(self):
        s = FaultTolerantSession(self.n)
        s.auth = ("admin", "admin")
        self.debug("Starting manage agents task...")
        r = s.post(f"{PM_URL}/project/1/periodic_task/3/execute/")
        history_id = r.json()["history_id"]
        time.sleep(1)
        while True:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
            if r.json()["status"] == "OK":
                break
            time.sleep(REQ_SLEEP_TIME)
        self.debug("Manage agents success")

    ### SSH Cleanup ###

    def kill_leftover_agents(self):
        self.debug("Killing leftover agents...")
        subprocess.run(
            [
                "ssh",
                self.ssh_server,
                f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.debug("Killed leftover agents")

    def clear_dirs(self):
        self.debug("Deleting log/testcase directories...")
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
        self.debug("Log/testcase directories deleted")
