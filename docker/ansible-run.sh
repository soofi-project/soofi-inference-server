#!/bin/bash
set -e

# Volume mounts cause two platform-specific issues:
#   Windows NTFS: 0777 permissions — SSH refuses keys/config, Ansible ignores ansible.cfg
#   Linux: files owned by host UID (e.g. 1000), container runs as root (0) — SSH "Bad owner" error
# Fix: copy SSH dir and ansible.cfg to /tmp, set root ownership + correct permissions,
#      then run ansible-playbook with HOME=/tmp so SSH uses /tmp/.ssh instead of /root/.ssh.

# Fix SSH keys: Windows NTFS mounts have 0777 — copy to /tmp and chmod before loading
mkdir -p /tmp/.ssh
cp -r /root/.ssh/. /tmp/.ssh/
chmod 700 /tmp/.ssh
find /tmp/.ssh -type f -exec chmod 600 {} \;

# Ensure SSH config exists (ansible.cfg uses -F /tmp/.ssh/config)
touch /tmp/.ssh/config

# Remove macOS-only SSH options that OpenSSH on Linux does not support
sed -i '/UseKeychain/Id' /tmp/.ssh/config

# Start SSH agent and load private keys
# ssh-add prompts for passphrases via the terminal (requires interactive session: docker compose exec)
# ansible.cfg sets IdentitiesOnly=yes — SSH uses only agent keys, never /root/.ssh directly (0777)
eval "$(ssh-agent -s)" > /dev/null
for key in $(find /tmp/.ssh -maxdepth 1 -name 'id_*' ! -name '*.pub' -type f | sort); do
    ssh-add "$key"
done

# Fix ansible.cfg: Ansible ignores cfg files in world-writable directories (Windows NTFS mounts)
cp /ansible/ansible.cfg /tmp/ansible.cfg
chmod 600 /tmp/ansible.cfg

# HOME=/tmp: SSH resolves ~/.ssh to /tmp/.ssh (the fixed copy) — avoids "Bad owner" on Linux
# and "permissions too open" on Windows NTFS
HOME=/tmp ANSIBLE_CONFIG=/tmp/ansible.cfg ANSIBLE_COLLECTIONS_PATH=/root/.ansible/collections ansible-playbook "$@"
