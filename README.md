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

Run a command on all hosts:

```bash
ansible fluffi -f 1 -a "uptime"
```
