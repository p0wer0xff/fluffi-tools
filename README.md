## Files

- `fuzzgoat/` - example of binary and initial seed
- `analysis.ipynb` - data analysis notebook
- `ansible_hosts` - Ansible host file for managing FLUFFI containers and host
- `experiment.py` - CLI for starting an experiment on one host
- `extract.py` - consolidates data from `experiments/` directory into a single Parquet file
- `fluffi.py` - functions for managing FLUFFI instances
- `fuzzjob.py` - functions for managing FLUFFI fuzz jobs
- `manage.py` - CLI for managing FLUFFI instances
- `measurements.parquet` - data collected from all experiments
- `ssh_config` - SSH config file for FLUFFI containers and host
- `util.py` - functions for fault tolerant SSH, SCP, SQL, and HTTP clients

## Server Assignments

Run 1:

- `1021-5` - Constant / FLUFFI
- `1021-6` - FAST / FLUFFI
- `1021-7` - Constant / Round-Robin
- `1021-8` - FAST / Round-Robin

Run 2:

- `1021-5` - Constant / AFLFast
- `1021-6` - FAST / AFLFast
- `1021-7` - Constant / AFLFast
- `1021-8` - FAST / AFLFast

## Setup

```bash
cp ssh_config ~/.ssh/config
sudo cp ansible_hosts /etc/ansible/hosts
```

## Useful Commands

```bash
ansible fluffi -f 1 -a "uptime"
watch -n 30 "ansible workers -f 1 -a 'uptime'"
nohup python3 experiment.py run1 5 &
```
