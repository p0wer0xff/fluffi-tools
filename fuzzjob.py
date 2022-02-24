import logging
import time

import fluffi
import util

# Constants
DB_FUZZJOB_FMT = "fluffi_{}"

# Get logger
log = logging.getLogger("fluffi")


class Fuzzjob:
    def __init__(self, f, id, name):
        self.f = f
        self.id = id
        self.name = name
        self.db = DB_FUZZJOB_FMT.format(name)

    ### Fluffi Web ###

    def archive(self):
        log.debug(f"Archiving fuzzjob {self.name}...")
        self.f.s.post(
            f"{fluffi.FLUFFI_URL}/projects/archive/{self.id}", expect_str="Step 0/4"
        )
        while True:
            r = self.f.s.get(f"{fluffi.FLUFFI_URL}/progressArchiveFuzzjob")
            if "5/5" in r.text:
                break
            time.sleep(util.REQ_SLEEP_TIME)
        log.debug(f"Fuzzjob {self.name} archived")

    def set_gre(self, gen, run, eva):
        log.debug(f"Setting GRE to {gen}, {run}, {eva} for {self.name}...")
        r = self.f.s.post(
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
