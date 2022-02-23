import logging
import os
import re
import socket
import subprocess
import time

import pymysql

import util

# Constants
FLUFFI_PATH_FMT = os.path.expanduser("~/fluffi{}")
LOCATION_FMT = "1021-{}"
SSH_MASTER_FMT = "master{}"
SSH_WORKER_FMT = "worker{}"
WORKER_NAME_FMT = "fluffi-1021-{}-Linux1"
ARCH = "x64"
FLUFFI_URL = "http://web.fluffi:8880"
PM_URL = "http://pole.fluffi:8888/api/v2"
DB_NAME = "fluffi_gm"

# Get logger
log = logging.getLogger("fluffi-tools")


class Fuzzjob:
    def __init__(self, id, name, db):
        self.id = id
        self.name = name
        self.db = db


class FluffiInstance:
    def __init__(self, n):
        # Set members
        self.n = n
        self.fluffi_path = FLUFFI_PATH_FMT.format(self.n)
        self.location = LOCATION_FMT.format(self.n)
        self.worker_name = WORKER_NAME_FMT.format(self.n)

        # Create SSH connections
        self.ssh_master, self.sftp_master, self.master_addr = util.ssh_connect(
            SSH_MASTER_FMT.format(self.n)
        )
        self.ssh_worker, self.sftp_worker, _ = util.ssh_connect(
            SSH_WORKER_FMT.format(self.n)
        )

        # Connect to DB
        self.db = pymysql.connect(host=self.master_addr, user=DB_NAME, password=DB_NAME)

        # Check the proxy and initialize the session
        self.check_proxy()
        self.s = util.FaultTolerantSession(self)
        self.s.get(FLUFFI_URL)

    # Close SSH and DB sessions on destruction
    def __del__(self):
        self.sftp_master.close()
        self.sftp_worker.close()
        self.ssh_master.close()
        self.ssh_worker.close()
        self.db.close()

    # Add location to log messages
    def __log(self, msg):
        return f"{self.location}: {msg}"

    def debug(self, msg):
        return log.debug(self.__log(msg))

    def info(self, msg):
        return log.info(self.__log(msg))

    def warn(self, msg):
        return log.warn(self.__log(msg))

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
        self.sftp_worker.put(
            f"{self.fluffi_path}/core/x86-64/bin/fluffi.zip",
            f"/home/fluffi_linux_user/fluffi/persistent/{ARCH}/fluffi.zip",
        )
        self.ssh_worker.exec_command(
            "cd /home/fluffi_linux_user/fluffi/persistent/x64 && unzip -o fluffi.zip",
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
        fuzzjobs = self.get_fuzzjobs()
        for fuzzjob in fuzzjobs:
            self.set_gre(fuzzjob, 0, 0, 0)
        self.set_lm(0)
        self.kill_leftover_agents()
        for fuzzjob in fuzzjobs:
            self.archive_fuzzjob(fuzzjob)
        self.clear_dirs()
        self.info("Stopped")

    def all(self, fuzzjob_name_prefix, target_path, module_path, seed_path):
        self.down()
        self.deploy()
        self.up(fuzzjob_name_prefix, target_path, module_path, seed_path)

    ### SSH ###

    def check_proxy(self):
        # Check if the port is open
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((self.master_addr, util.PROXY_PORT))
            s.close()
            self.info("Proxy is open")
            return
        except Exception as e:
            self.warn(f"Failed connecting to proxy: {e}")

        # Start proxy server
        _, stdout, stderr = self.ssh_master.exec_command(
            f"ssh localhost -D 0.0.0.0:{util.PROXY_PORT} -N -f"
        )
        if stdout.channel.recv_exit_status() != 0:
            self.error(f"Error starting proxy: {stderr.read()}")
            raise Exception("Error starting proxy")
        time.sleep(1)
        self.debug(f"Started proxy")
        self.check_proxy()

    def kill_leftover_agents(self):
        self.debug("Killing leftover agents...")
        self.ssh_worker.exec_command(
            f"pkill -f '/home/fluffi_linux_user/fluffi/persistent/{ARCH}/'",
        )
        self.debug("Killed leftover agents")

    def clear_dirs(self):
        self.debug("Deleting log/testcase directories...")
        self.ssh_worker.exec_command(
            "rm -rf /home/fluffi_linux_user/fluffi/persistent/x64/logs /home/fluffi_linux_user/fluffi/persistent/x64/testcaseFiles"
        )
        self.debug("Log/testcase directories deleted")

    ### Fluffi Web ###

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
            time.sleep(util.REQ_SLEEP_TIME)
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
        self.debug(f"Setting GRE to {gen}, {run}, {eva} for {fuzzjob.name}...")
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
                self.error(
                    f"Error setting GRE to {gen}, {run}, {eva} for {fuzzjob.name}: {r.text}"
                )
                continue
            break
        self.manage_agents()
        self.debug(f"GRE set to {gen}, {run}, {eva} for {fuzzjob.name}")

    ### Polemarch ###

    def manage_agents(self):
        s = util.FaultTolerantSession(self)
        s.auth = ("admin", "admin")
        self.debug("Starting manage agents task...")
        r = s.post(f"{PM_URL}/project/1/periodic_task/3/execute/")
        history_id = r.json()["history_id"]
        time.sleep(1)
        while True:
            r = s.get(f"{PM_URL}/project/1/history/{history_id}")
            if r.json()["status"] == "OK":
                break
            time.sleep(util.REQ_SLEEP_TIME)
        self.debug("Manage agents success")

    ### DB ###

    def get_fuzzjobs(self):
        self.db.select_db(DB_NAME)
        fuzzjobs = []
        with self.db.cursor() as c:
            c.execute("SELECT ID, name, DBName from fuzzjob")
            for id, name, db in c.fetchall():
                self.debug(f"Found fuzzjob with ID {id} and name{name}")
                fuzzjobs.append(Fuzzjob(id, name, db))
        return fuzzjobs
