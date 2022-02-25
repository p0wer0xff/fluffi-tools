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
        self.pid_cpu_time = {}
        self.dead_cpu_time = 0

    ### SSH ###

    def get_dump(self, local_path, clean=True):
        log.debug(f"Retrieving dump for fuzzjob {self.name}...")
        self.f.ssh_master.get(self.dump_path, local_path)
        if clean:
            self.f.ssh_master.exec_command(f"rm {self.dump_path}", check=True)
        log.debug(f"Retrieved dump for fuzzjob {self.name}")

    ### Fluffi Web ###

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

    ### Data ###

    def get_stats(self):
        log.debug(f"Getting stats for {self.name}...")
        d = {}

        # Get CPU time
        _, stdout, _ = self.f.ssh_worker.exec_command(
            f"ps --cumulative -ax | grep {self.f.location} | grep -v grep | awk '{{print $1, $4}}'",
            check=True,
        )
        d["cpu_time"] = 0
        pid_cpu_time = {}
        for match in re.findall(r"(\d+) (\d+):(\d+)", stdout.read().decode()):
            pid, mins, secs = map(int, match)
            pid_cpu_time[pid] = (mins * 60) + secs
            d["cpu_time"] += pid_cpu_time[pid]
        log.debug(f"{len(pid_cpu_time) // 2} agents are running")
        for pid, cpu_time in self.pid_cpu_time.items():
            if pid not in pid_cpu_time:
                log.debug(f"Dead PID {pid}, adding its time of {cpu_time}")
                self.dead_cpu_time += cpu_time
        d["cpu_time"] += self.dead_cpu_time
        self.pid_cpu_time = pid_cpu_time

        # Get stats from Fluffi web
        while True:
            r = self.f.s.get(
                f"{fluffi.FLUFFI_URL}/projects/view/{self.id}",
                expect_str="General Information",
            )
            matches = re.findall(r'<td style="text-align: center;">(.+)</td>', r.text)
            try:
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
                d["active_run"] = int(matches[11])
                d["active_eva"] = int(matches[12])
                d["active_gen"] = int(matches[13])
                break
            except Exception as e:
                log.error(f"Error getting stats for {self.name}: {e}")
                time.sleep(util.SLEEP_TIME)

        # Get number of paths
        # d["paths"] = self.f.db.query_one(
        #     "SELECT COUNT(*) FROM edge_coverage", self.db_name
        # )[0]

        log.debug(f"Got stats for {self.name}")
        return d
