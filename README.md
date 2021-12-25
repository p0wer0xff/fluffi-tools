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
