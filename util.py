import logging
import os
import time

import paramiko
import pymysql
import requests

# Constants
PROXY_PORT = 6969
FLUFFI_DB_ERROR_STR = "Error: Database connection failed"
REQ_SLEEP_TIME = 0.25
REQ_TRIES = 3

# Get logger
log = logging.getLogger("fluffi")

# Get SSH config
ssh_config = paramiko.SSHConfig()
with open(os.path.expanduser("~/.ssh/config")) as f:
    ssh_config.parse(f)


def get_ssh_addr(hostname):
    return ssh_config.lookup(hostname)["hostname"]


class FaultTolerantSession(requests.Session):
    def __init__(self, fluffi, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fluffi = fluffi
        proxies = {
            "http": f"socks5h://{fluffi.master_addr}:{PROXY_PORT}",
            "https": f"socks5h://{fluffi.master_addr}:{PROXY_PORT}",
        }
        self.proxies.update(proxies)

    def request(self, *args, **kwargs):
        expect_str = kwargs.pop("expect_str", None)
        sleep_time = REQ_SLEEP_TIME
        while True:
            for _ in range(REQ_TRIES):
                try:
                    r = super().request(*args, **kwargs)
                except Exception as e:
                    log.warn(f"Request exception: {e}")
                else:
                    if FLUFFI_DB_ERROR_STR in r.text:
                        log.warn("Fluffi web DB connection failed")
                    elif not r.ok:
                        log.warn(f"Request got status code {r.status_code}")
                    elif expect_str is not None and expect_str not in r.text:
                        log.error(f"String '{expect_str}' not found in response")
                    else:
                        return r
                time.sleep(sleep_time)
                sleep_time *= 2
            log.error(f"Request failed {REQ_TRIES} times, checking proxy")
            self.fluffi.check_proxy()


class FaultTolerantSSHAndSFTPClient:
    def __init__(self, hostname):
        self.hostname = hostname
        host_config = ssh_config.lookup(self.hostname)
        self.host_config = {
            "hostname": host_config["hostname"],
            "username": host_config["user"],
            "key_filename": host_config["identityfile"],
        }
        self.__connect(False)

    def __del__(self):
        self.__close()

    def __close(self):
        try:
            self.sftp.close()
            self.ssh.close()
        except Exception as e:
            log.error(f"Error closing SSH/SFTP for {self.hostname}: {e}")

    def __connect(self, reconnect=True):
        if reconnect:
            self.__close()
        sleep_time = REQ_SLEEP_TIME
        while True:
            log.debug(f"Connecting to SSH/SFTP for {self.hostname}...")
            try:
                self.ssh = paramiko.SSHClient()
                self.ssh.load_system_host_keys()
                self.ssh.connect(**self.host_config)
                self.sftp = self.ssh.open_sftp()
                break
            except Exception as e:
                log.error(f"Error connecting to SSH/SFTP for {self.hostname}: {e}")
            time.sleep(sleep_time)
            sleep_time *= 2
        log.debug(f"Connected to SSH/SFTP for {self.hostname}")

    def __sftp(self, func, *args, **kwargs):
        sleep_time = REQ_SLEEP_TIME
        while True:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                log.error(f"SFTP error on {self.hostname}: {e}")
                self.__connect()
            time.sleep(sleep_time)
            sleep_time *= 2

    def exec_command(self, *args, **kwargs):
        check = kwargs.pop("check", False)
        sleep_time = REQ_SLEEP_TIME
        while True:
            try:
                stdin, stdout, stderr = self.ssh.exec_command(*args, **kwargs)
            except Exception as e:
                log.error(
                    f"Error executing {self.hostname} SSH command '{args[0]}': {e}"
                )
                self.__connect()
            else:
                if check and stdout.channel.recv_exit_status() != 0:
                    log.error(
                        f"Error executing {self.hostname} SSH command '{args[0]}': {stdout.read()}"
                    )
                else:
                    return stdin, stdout, stderr
            time.sleep(sleep_time)
            sleep_time *= 2

    def get(self, *args, **kwargs):
        return self.__sftp(self.sftp.get, *args, **kwargs)

    def put(self, *args, **kwargs):
        return self.__sftp(self.sftp.put, *args, **kwargs)


class FaultTolerantDBClient(pymysql.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__connect()

    def __connect(self):
        log.debug("Connecting to DB...")
        sleep_time = REQ_SLEEP_TIME
        while True:
            try:
                super().ping()
                log.debug("Connected to DB")
                break
            except Exception as e:
                log.error(f"Error connecting to DB: {e}")
            time.sleep(sleep_time)
            sleep_time *= 2

    def __query(self, func_name, query):
        sleep_time = REQ_SLEEP_TIME
        while True:
            try:
                with self.cursor() as c:
                    c.execute(query)
                    return getattr(c, func_name)()
            except Exception as e:
                log.error(f"Error for query '{query}': {e}")
            self.__connect()
            time.sleep(sleep_time)
            sleep_time *= 2

    def query_one(self, query):
        return self.__query("fetchone", query)

    def query_all(self, query):
        return self.__query("fetchall", query)
