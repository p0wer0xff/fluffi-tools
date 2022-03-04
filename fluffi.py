import logging
import os
import re
import socket
import subprocess
import time

import util
from fuzzjob import Fuzzjob

# Constants
FLUFFI_PATH_FMT = os.path.expanduser("~/fluffi{}/")
LOCATION_FMT = "1021-{}"
SSH_HOST_FMT = "host{}"
SSH_MASTER_FMT = "master{}"
SSH_WORKER_FMT = "worker{}"
WORKER_NAME_FMT = "fluffi-1021-{}-Linux1"
ARCH = "x64"
DEPLOY_ZIP_NAME = "fluffi.zip"
FLUFFI_DIR = "/home/fluffi_linux_user/fluffi/persistent/"
FLUFFI_ARCH_DIR = os.path.join(FLUFFI_DIR, ARCH)
SUT_PATH = os.path.join(FLUFFI_DIR, "SUT/")
FLUFFI_URL = "http://web.fluffi:8880"
PM_URL = "http://pole.fluffi:8888/api/v2"
DB_NAME = "fluffi_gm"
LM = 1

# Get logger
log = logging.getLogger("fluffi")


class Instance:
    def __init__(self, n):
        # Set members
        self.n = n
        self.fluffi_path = FLUFFI_PATH_FMT.format(self.n)
        self.location = LOCATION_FMT.format(self.n)
        self.worker_name = WORKER_NAME_FMT.format(self.n)
        self.master_addr = util.get_ssh_addr(SSH_MASTER_FMT.format(self.n))

        # Connect to SSH and DB
        self.ssh_host = util.FaultTolerantSSHAndSFTPClient(SSH_HOST_FMT.format(self.n))
        self.ssh_master = util.FaultTolerantSSHAndSFTPClient(
            SSH_MASTER_FMT.format(self.n)
        )
        self.ssh_worker = util.FaultTolerantSSHAndSFTPClient(
            SSH_WORKER_FMT.format(self.n)
        )
        self.db = util.FaultTolerantDBClient(
            host=self.master_addr, user=DB_NAME, password=DB_NAME
        )

        # Check the proxy and initialize the session
        self.check_proxy()
        self.s = util.FaultTolerantSession(self)
        self.s.get(FLUFFI_URL)

    ### High Level Functionality ###

    def deploy(self, clean=True):
        log.debug("Deploying...")

        # Clean old build
        if clean:
            log.debug("Cleaning old build...")
            subprocess.run(
                ["rm", "-rf", os.path.join(self.fluffi_path, "core/x86-64/")],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.debug("Old build cleaned")

        # Compile new build
        log.debug("Compiling new build...")
        subprocess.run(
            ["./make_dep.sh"],
            cwd=os.path.join(self.fluffi_path, "core/dependencies/easylogging/"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["sudo", "./buildAll.sh"],
            cwd=os.path.join(self.fluffi_path, "build/ubuntu_based/"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log.debug("New build compiled")

        # Zip, SCP, and unzip
        log.debug("Transferring new build...")
        subprocess.run(
            ["zip", "-r", DEPLOY_ZIP_NAME, "."],
            cwd=os.path.join(self.fluffi_path, "core/x86-64/bin/"),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.ssh_worker.put(
            os.path.join(self.fluffi_path, "core/x86-64/bin/", DEPLOY_ZIP_NAME),
            os.path.join(FLUFFI_ARCH_DIR, DEPLOY_ZIP_NAME),
        )
        self.ssh_worker.exec_command(
            f"cd {FLUFFI_ARCH_DIR} && unzip -o {DEPLOY_ZIP_NAME}", check=True
        )
        log.debug("New build transferred")

        log.debug("Deployed")

    def up(
        self,
        name_prefix,
        target_path,
        module,
        seeds,
        library_path=None,
        linker_path=None,
    ):
        log.debug(f"Starting fuzzjob with prefix {name_prefix}...")
        self.set_kernel_vals()
        fuzzjob = self.new_fuzzjob(
            name_prefix, target_path, module, seeds, library_path, linker_path
        )
        self.set_lm(LM)
        fuzzjob.set_gre(2, 11, 11)
        log.debug(f"Started fuzzjob named {fuzzjob.name}")
        return fuzzjob

    def down(self):
        log.debug("Stopping...")
        fuzzjobs = self.get_fuzzjobs()
        for fuzzjob in fuzzjobs:
            fuzzjob.set_gre(0, 0, 0)
        self.set_lm(0)
        self.kill_leftover_agents()
        for fuzzjob in fuzzjobs:
            fuzzjob.archive()
        self.clear_dirs()
        log.debug("Stopped")

    def all(self, name_prefix, target_path, module, seeds, library_path=None):
        self.down()
        self.deploy()
        self.up(name_prefix, target_path, module, seeds, library_path)

    ### SSH ###

    def check_proxy(self):
        # Check if the port is open
        log.debug("Checking proxy port...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((self.master_addr, util.PROXY_PORT))
            s.close()
            log.info("Proxy is open")
            return
        except Exception as e:
            log.warn(f"Failed connecting to proxy: {e}")

        # Start proxy server
        log.debug("Starting proxy...")
        self.ssh_master.exec_command(
            f"ssh localhost -D 0.0.0.0:{util.PROXY_PORT} -N -f", check=True
        )
        time.sleep(1)
        log.info(f"Started proxy")
        self.check_proxy()

    def kill_leftover_agents(self):
        log.debug("Killing leftover agents...")
        self.ssh_worker.exec_command(f"pkill -f '{FLUFFI_ARCH_DIR}'")
        log.debug("Killed leftover agents")

    def clear_dirs(self):
        log.debug("Deleting log/testcase directories...")
        self.ssh_worker.exec_command(
            f"rm -rf {os.path.join(FLUFFI_ARCH_DIR, 'logs/')} {os.path.join(FLUFFI_ARCH_DIR, 'testcaseFiles/')}"
        )
        log.debug("Log/testcase directories deleted")

    def set_kernel_vals(self):
        log.debug("Setting kernel values...")
        self.ssh_host.exec_command("sudo /home/maverick/bin/afl-setup.sh", check=True)
        log.debug("Kernel values set")

    ### Fluffi Web ###

    def new_fuzzjob(
        self,
        name_prefix,
        target_path,
        module,
        seeds,
        library_path=None,
        linker_path=None,
    ):
        name = f"{name_prefix}{int(time.time())}"
        log.debug(f"Creating new fuzzjob named {name}...")

        # Set command line
        cmd = os.path.join(SUT_PATH, target_path)
        if library_path is not None and linker_path is not None:
            cmd = f"{os.path.join(SUT_PATH, linker_path)} --library-path {os.path.join(SUT_PATH, library_path)} {cmd}"

        # Create fuzzjob with seeds
        data = [
            ("name", (None, name)),
            ("subtype", (None, "X64_Lin_DynRioSingle")),
            ("generatorTypes", (None, 0)),  # RadamsaMutator
            ("generatorTypes", (None, 100)),  # AFLMutator
            ("generatorTypes", (None, 0)),  # CaRRoTMutator
            ("generatorTypes", (None, 0)),  # HonggfuzzMutator
            ("generatorTypes", (None, 0)),  # OedipusMutator
            ("generatorTypes", (None, 0)),  # ExternalMutator
            ("evaluatorTypes", (None, 100)),  # CoverageEvaluator
            ("location", (None, self.location)),
            ("targetCMDLine", (None, cmd)),
            ("option_module", (None, "hangeTimeout")),
            ("option_module_value", (None, 5000)),
            ("targetModulesOnCreate", module),
            ("targetFile", (None, "")),
            ("basicBlockFile", (None, "")),
        ]
        for seed in seeds:
            data.append(("filename", seed))

        # Attempt to create
        sleep_time = util.SLEEP_TIME
        while True:
            r = self.s.post(
                f"{FLUFFI_URL}/projects/createProject",
                files=data,
                expect_str="Success!",
                no_retry=True,
            )
            time.sleep(1)
            fuzzjobs = self.get_fuzzjobs()
            fuzzjob = next(
                (fuzzjob for fuzzjob in fuzzjobs if fuzzjob.name == name), None
            )
            if fuzzjob is not None:
                break
            log.warn(f"Fuzzjob {name} wasn't created")
            time.sleep(util.SLEEP_TIME)
            sleep_time = util.get_sleep_time(sleep_time)

        # If timeout, wait until all testcases added
        if not r.ok:
            while fuzzjob.get_num_testcases() < len(seeds):
                time.sleep(5)

        log.debug(f"Fuzzjob named {name} created with ID {fuzzjob.id}")
        return fuzzjob

    def set_lm(self, num):
        log.debug(f"Setting LM to {num}...")
        self.s.post(
            f"{FLUFFI_URL}/systems/configureSystemInstances/{self.worker_name}",
            files={
                "localManager_lm": (None, num),
                "localManager_lm_arch": (None, ARCH),
            },
            expect_str="Success!",
        )
        self.manage_agents()
        log.debug(f"LM set to {num}")

    ### Polemarch ###

    def manage_agents(self):
        log.debug("Starting manage agents task...")
        s = util.FaultTolerantSession(self)
        s.auth = ("admin", "admin")
        r = s.post(
            f"{PM_URL}/project/1/periodic_task/3/execute/",
            expect_str="Started at inventory",
        )
        history_id = r.json()["history_id"]
        time.sleep(2)
        while True:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
            if r.json()["status"] == "OK":
                break
            time.sleep(util.SLEEP_TIME)
        log.debug("Manage agents success")

    ### DB ###

    def get_fuzzjobs(self):
        log.debug("Fetching fuzzjobs...")
        rows = self.db.query_all("SELECT ID, name FROM fuzzjob", DB_NAME)
        fuzzjobs = []
        for id, name in rows:
            log.debug(f"Found fuzzjob with ID {id} and name {name}")
            fuzzjobs.append(Fuzzjob(self, id, name))
        log.debug("Fuzzjobs fetched")
        return fuzzjobs
