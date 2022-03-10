import logging
import re
import time

import fluffi
import util

# Constants
DB_FUZZJOB_FMT = "fluffi_{}"
DUMP_PATH_FMT = "/srv/fluffi/data/ftp/files/archive/{}.sql.gz"
ADJUST_AGENTS = False
MANAGE_AGENTS_INTERVAL = 1 * 60  # 1 minute
LOAD_HIGH = 15.8
LOAD_LOW = 14.3
LOAD_COUNTER_MIN = 6
GEN_INIT = 2
RUN_INIT = 15
EVA_INIT = 15

# Get logger
log = logging.getLogger("fluffi")


class Fuzzjob:
    def __init__(self, f, id, name):
        self.f = f
        self.id = id
        self.name = name
        self.db_name = DB_FUZZJOB_FMT.format(self.name)
        self.dump_path = DUMP_PATH_FMT.format(self.db_name)
        self.gen = GEN_INIT
        self.run = RUN_INIT
        self.eva = EVA_INIT
        self.pid_cpu_time = {}
        self.dead_cpu_time = 0
        self.last_manage_time = time.time()
        self.last_adjust_gre_time = time.time()
        self.load_high_counter = 0
        self.load_low_counter = 0

    # --- SSH ---

    def get_dump(self, local_path, clean=True):
        log.debug(f"Retrieving dump for fuzzjob {self.name}...")
        self.f.ssh_master.get(self.dump_path, local_path)
        if clean:
            self.f.ssh_master.exec_command(f"rm {self.dump_path}", check=True)
        log.debug(f"Retrieved dump for fuzzjob {self.name}")

    def get_cpu_time(self):
        log.debug("Getting CPU time...")
        cpu_time_total = 0
        pid_cpu_time = {}

        # Get the new PIDs and time
        _, stdout, _ = self.f.ssh_worker.exec_command(
            f"ps --cumulative -ax | grep {self.f.location} "
            f"| grep -v grep | awk '{{print $1, $4}}'",
            check=True,
        )
        for match in re.findall(r"(\d+) (\d+):(\d+)", stdout.read().decode()):
            pid, mins, secs = map(int, match)
            pid_cpu_time[pid] = (mins * 60) + secs
            cpu_time_total += pid_cpu_time[pid]
        agents = len(pid_cpu_time) // 2

        # Check for any dead processes
        for pid, cpu_time in self.pid_cpu_time.items():
            if pid not in pid_cpu_time:
                log.debug(f"Dead PID {pid}, adding its time of {cpu_time}")
                self.dead_cpu_time += cpu_time
        cpu_time_total += self.dead_cpu_time
        self.pid_cpu_time = pid_cpu_time

        # Attempt manage agents if incorrect number running
        if (
            agents != sum([fluffi.LM, self.gen, self.run, self.eva])
            and (time.time() - self.last_manage_time) > MANAGE_AGENTS_INTERVAL
        ):
            log.warn(f"Incorrect number of agents ({agents}) are running")
            self.f.manage_agents()
            self.last_manage_time = time.time()

        # Adjust GRE based on load
        if (
            ADJUST_AGENTS
            and (time.time() - self.last_manage_time) > MANAGE_AGENTS_INTERVAL
        ):
            load = self.f.get_load()
            if load > LOAD_HIGH:
                self.load_high_counter += 1
                self.load_low_counter = 0
                if self.load_high_counter >= LOAD_COUNTER_MIN:
                    self.run -= 1
                    self.eva -= 1
                    log.warn(f"Decreasing RE agents to {self.run}")
                    self.set_gre()
                    self.load_high_counter = 0
            elif load < LOAD_LOW:
                self.load_high_counter = 0
                self.load_low_counter += 1
                if self.load_low_counter >= LOAD_COUNTER_MIN:
                    self.run += 1
                    self.eva += 1
                    log.warn(f"Increasing RE agents to {self.run}")
                    self.set_gre()
                    self.load_low_counter = 0
            else:
                self.load_high_counter = 0
                self.load_low_counter = 0
        else:
            self.load_high_counter = 0
            self.load_low_counter = 0

        log.debug(f"Got CPU time of {cpu_time_total / 60:.2f} minutes")
        return cpu_time_total

    # --- Fluffi Web ---

    def archive(self):
        while True:
            log.debug(f"Archiving fuzzjob {self.name}...")
            self.f.s.post(
                f"{fluffi.FLUFFI_URL}/projects/archive/{self.id}", expect_str="Step 0/4"
            )
            done = False
            start = time.time()
            time.sleep(1)
            while True:
                self.f.s.get(f"{fluffi.FLUFFI_URL}/progressArchiveFuzzjob")
                _, stdout, _ = self.f.ssh_master.exec_command(
                    "ls /srv/fluffi/data/ftp/files/archive/", check=True
                )
                if self.name in stdout.read().decode():
                    done = True
                    break
                elif (time.time() - start) > 20:
                    log.warn(f"Archive for {self.name} taking awhile, trying again")
                    break
                time.sleep(util.SLEEP_TIME)
            if done:
                break
        time.sleep(5)
        log.debug(f"Fuzzjob {self.name} archived")

    def set_gre(self, down=False):
        gen = 0 if down else self.gen
        run = 0 if down else self.run
        eva = 0 if down else self.eva
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
        self.last_manage_time = time.time()
        log.debug(f"GRE set to {gen}, {run}, {eva} for {self.name}")

    # --- DB ---

    def get_num_testcases(self):
        log.debug(f"Getting number of testcases for {self.name}...")
        testcases = self.f.db.query_one(
            "SELECT COUNT(*) FROM interesting_testcases", self.db_name
        )[0]
        log.debug(f"Got {testcases} testcases for {self.name}")
        return testcases

    # --- Data Collection ---

    def get_stats(self):
        log.debug(f"Getting stats for {self.name}...")
        d = {}

        # Fluffi web metrics
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

        # Edge coverage from DB
        d["paths"] = self.f.db.query_one(
            "SELECT COUNT(*) FROM edge_coverage", self.db_name
        )[0]

        # Load average
        d["load"] = self.f.get_load()
        if d["load"] > 17:
            log.warn(f"Load average is at {d['load']}")

        # RAM usage
        _, stdout, _ = self.f.ssh_worker.exec_command(
            "free | grep Mem | awk '{print $3/$2 * 100.0}'", check=True
        )
        d["memory_used"] = float(stdout.read().decode().strip())
        if d["memory_used"] > 80:
            log.warn(f"Memory usage is at {d['memory_used']}%")

        # Disk usage
        _, stdout, _ = self.f.ssh_worker.exec_command(
            "df / | tail -n +2 | awk '{ print $5 }'", check=True
        )
        d["disk_used"] = int(stdout.read().decode().strip()[:-1])
        if d["disk_used"] > 70:
            log.warn(f"Disk usage is at {d['disk_used']}%")

        # RAM disk usage
        _, stdout, _ = self.f.ssh_worker.exec_command(
            "df /home/fluffi_linux_user/fluffi/ramdisk "
            "| tail -n +2 | awk '{ print $5 }'",
            check=True,
        )
        d["ramdisk_used"] = int(stdout.read().decode().strip()[:-1])
        if d["ramdisk_used"] > 70:
            log.warn(f"RAM disk usage is at {d['ramdisk_used']}%")

        log.debug(f"Got stats for {self.name}")
        return d
