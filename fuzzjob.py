import logging
import re
import time

import fluffi
import util

# Constants
DB_FUZZJOB_FMT = "fluffi_{}"
DUMP_PATH_FMT = "/srv/fluffi/data/ftp/files/archive/{}.sql.gz"

# Get logger
log = logging.getLogger("fluffi")


class Fuzzjob:
    def __init__(self, f, id, name):
        self.f = f
        self.id = id
        self.name = name
        self.db_name = DB_FUZZJOB_FMT.format(self.name)
        self.dump_path = DUMP_PATH_FMT.format(self.db_name)

    def get_dump(self, local_path, clean=True):
        log.debug(f"Retrieving dump for fuzzjob {self.name}...")
        self.f.ssh_master.get(self.dump_path, local_path)
        if clean:
            self.f.ssh_master.exec_command(f"rm {self.dump_path}", check=True)
        log.debug(f"Retrieved dump for fuzzjob {self.name}")

    def archive(self):
        log.debug(f"Archiving fuzzjob {self.name}...")
        self.f.s.post(
            f"{fluffi.FLUFFI_URL}/projects/archive/{self.id}", expect_str="Step 0/4"
        )
        time.sleep(1)
        while True:
            r = self.f.s.get(f"{fluffi.FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(util.SLEEP_TIME)
        log.debug(f"Fuzzjob {self.name} archived")

    def set_gre(self, gen, run, eva):
        log.debug(f"Setting GRE to {gen}, {run}, {eva} for {self.name}...")
        self.f.s.post(
            f"{fluffi.FLUFFI_URL}/systems/configureFuzzjobInstances/{self.name}",
            files={
                f"{self.f.worker_name}_tg": (None, gen),
                f"{self.f.worker_name}_tg_arch": (None, fluffi.ARCH),
                f"{self.f.worker_name}_tr": (None, run),
                f"{self.f.worker_name}_tr_arch": (None, fluffi.ARCH),
                f"{self.f.worker_name}_te": (None, eva),
                f"{self.f.worker_name}_te_arch": (None, fluffi.ARCH),
            },
            expect_str="Success!",
        )
        self.f.manage_agents()
        log.debug(f"GRE set to {gen}, {run}, {eva} for {self.name}")

    def get_num_testcases(self):
        log.debug(f"Getting number of testcases for {self.name}...")
        testcases = self.f.db.query_one(
            "SELECT COUNT(*) FROM interesting_testcases", self.db_name
        )[0]
        log.debug(f"Got {testcases} testcases for {self.name}")
        return testcases

    def get_stats(self):
        log.debug(f"Getting stats for {self.name}...")
        d = {}
        r = self.f.s.get(
            f"{fluffi.FLUFFI_URL}/projects/view/{self.id}",
            expect_str="General Information",
        )
        matches = re.findall(r'<td style="text-align: center;">(.+)</td>', r.text)
        d["completed_testcases"] = int(matches[0])
        d["population"] = int(matches[1].split(" /")[0])
        d["access_violations_total"] = int(matches[2])
        d["access_violations_unique"] = int(matches[3])
        d["crashes_total"] = int(matches[4])
        d["crashes_unique"] = int(matches[5])
        d["hangs"] = int(matches[6])
        d["no_response"] = int(matches[7])
        d["covered_blocks"] = int(matches[8])
        d["active_lm"] = int(matches[9])
        try:
            d["active_run"] = int(matches[11])
            d["active_eva"] = int(matches[12])
            d["active_gen"] = int(matches[13])
        except:
            log.warn(f"Could not get active agents for {self.name}")
            d["active_run"] = 0
            d["active_eva"] = 0
            d["active_gen"] = 0
        d["paths"] = self.f.db.query_one(
            "SELECT COUNT(*) FROM edge_coverage", self.db_name
        )[0]
        _, stdout, _ = self.f.ssh_worker.exec_command(
            "awk '{ print $1 }' /proc/loadavg", check=True
        )
        d["load"] = float(stdout.read().decode().strip())
        _, stdout, _ = self.f.ssh_worker.exec_command(
            "free | grep Mem | awk '{print $3/$2 * 100.0}'", check=True
        )
        d["memory_used"] = float(stdout.read().decode().strip())
        log.debug(f"Got stats for {self.name}")
        return d
