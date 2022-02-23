import logging
import os
import time

import paramiko
import requests

# Constants
PROXY_PORT = 6969
FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25
REQ_TRIES = 5

# Get logger
log = logging.getLogger("fluffi-tools")

# Get SSH config
ssh_config = paramiko.SSHConfig()
with open(os.path.expanduser("~/.ssh/config")) as f:
    ssh_config.parse(f)


def ssh_connect(hostname):
    host_config = ssh_config.lookup(hostname)
    host_config = {
        "hostname": host_config["hostname"],
        "username": host_config["user"],
        "key_filename": host_config["identityfile"],
    }
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(**host_config)
    return client, client.open_sftp(), host_config["hostname"]


class FaultTolerantSession(requests.Session):
    def __init__(self, fluffi, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fluffi = fluffi

        # Use SSH proxy server
        proxies = {
            "http": f"socks5h://{fluffi.master_addr}:{PROXY_PORT}",
            "https": f"socks5h://{fluffi.master_addr}:{PROXY_PORT}",
        }
        self.proxies.update(proxies)

    # Add location to log messages
    def __log(self, msg):
        return f"{self.fluffi.location}: {msg}"

    def warn(self, msg):
        return log.warn(self.__log(msg))

    def error(self, msg):
        return log.error(self.__log(msg))

    # Perform fault tolerant requests
    def request(self, *args, **kwargs):
        for _ in range(REQ_TRIES):
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
        self.error(f"Request failed {REQ_TRIES} times, checking proxy")
        self.fluffi.check_proxy()
        self.request(*args, **kwargs)
