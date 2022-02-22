import time

import requests

FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25


class FaultTolerantSession(requests.Session):
    def request(self, *args, **kwargs):
        while True:
            try:
                r = super().request(*args, **kwargs)
            except Exception as e:
                time.sleep(REQ_SLEEP_TIME)
                continue
            if FLUFFI_DB_ERROR_STR in r.text:
                time.sleep(REQ_SLEEP_TIME)
                continue
            if r.ok:
                return r
            time.sleep(REQ_SLEEP_TIME)
