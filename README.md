## Servers

- `1021-5` - greedy scheduler + no power schedule
- `1021-6` - greedy scheduler + power schedule
- `1021-7` - round robin scheduler + no power schedule
- `1021-8` - round robin scheduler + power schedule

## Setup

```bash
cp ssh_config ~/.ssh/config
sudo cp ansible_hosts /etc/ansible/hosts
```

## Commands

```bash
ansible fluffi -f 1 -a "uptime"
watch -n 30 "ansible workers -f 1 -a 'uptime'"
nohup python3 experiment.py run1 5 &
```
