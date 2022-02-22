import logging
import time

import requests

# Constants
FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25

# Get logger
log = logging.getLogger("fluffi-tools")


class FaultTolerantSession(requests.Session):
    def request(self, *args, **kwargs):
        while True:
            try:
                r = super().request(*args, **kwargs)
            except Exception as e:
                log.warn(f"Request exception: {e}")
                time.sleep(REQ_SLEEP_TIME)
                continue
            if FLUFFI_DB_ERROR_STR in r.text:
                log.warn("Fluffi web app DB connection failed")
            elif not r.ok:
                log.warn(f"Request got status code {r.status_code}")
            else:
                return r
            time.sleep(REQ_SLEEP_TIME)
