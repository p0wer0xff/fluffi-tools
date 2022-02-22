import logging
import subprocess
import time

import requests

# Constants
FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25
PROXY_PORT_BASE = 9000
SSH_SERVER_PREFIX = "worker"

# Get logger
log = logging.getLogger("fluffi-tools")


class FaultTolerantSession(requests.Session):
    def __init__(self, n, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Use SSH proxy server
        port = PROXY_PORT_BASE + n
        proxies = {
            "http": f"socks5h://127.0.0.1:{port}",
            "https": f"socks5h://127.0.0.1:{port}",
        }
        self.proxies.update(proxies)

    # Perform fault tolerant requests
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


def stop_proxy(n):
    port = PROXY_PORT_BASE + n
    subprocess.run(
        f"lsof -ti tcp:{port} | xargs kill",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log.debug(f"Stopped proxy on port {port}")


def start_proxy(n):
    stop_proxy(n)
    port = PROXY_PORT_BASE + n
    subprocess.run(
        f"ssh {SSH_SERVER_PREFIX}{n} -D {port} -N &",
        check=True,
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(0.5)
    log.debug(f"Started proxy on port {port}")
