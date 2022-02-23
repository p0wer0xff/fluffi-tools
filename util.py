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
log = logging.getLogger("fluffi")

# Get SSH config
ssh_config = paramiko.SSHConfig()
with open(os.path.expanduser("~/.ssh/config")) as f:
    ssh_config.parse(f)


def ssh_connect(hostname):
    log.debug(f"Connecting to {hostname} SSH server")
    host_config = ssh_config.lookup(hostname)
    host_config = {
        "hostname": host_config["hostname"],
        "username": host_config["user"],
        "key_filename": host_config["identityfile"],
    }
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(**host_config)
    log.debug(f"Connected to {hostname} SSH server")
    return client, client.open_sftp(), host_config["hostname"]

# Fault tolerant DB query
def db_query(db, query):
    while True:
        try:
            with db.cursor() as c:
                c.execute(query)
                return c.fetchall()
        except Exception as e:
            log.error(f"Error for query {query}: {e}")
        db.ping(reconnect=True)
        time.sleep(REQ_SLEEP_TIME)


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

    # Perform fault tolerant requests
    def request(self, *args, **kwargs):
        for _ in range(REQ_TRIES):
            try:
                r = super().request(*args, **kwargs)
            except Exception as e:
                log.warn(f"Request exception: {e}")
                time.sleep(REQ_SLEEP_TIME)
                continue
            if FLUFFI_DB_ERROR_STR in r.text:
                log.warn("Fluffi web DB connection failed")
            elif not r.ok:
                log.warn(f"Request got status code {r.status_code}")
            else:
                return r
            time.sleep(REQ_SLEEP_TIME)
        log.error(f"Request failed {REQ_TRIES} times, checking proxy")
        self.fluffi.check_proxy()
        self.request(*args, **kwargs)
