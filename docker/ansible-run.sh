#!/bin/bash
set -e

# Windows NTFS volume mounts have 0777 permissions, which causes two issues:
#   1. SSH refuses private keys with permissions too open (requires 600)
#   2. Ansible ignores ansible.cfg in world-writable directories
# Fix: copy both to /tmp and set correct permissions before running.

# Fix SSH keys: Windows NTFS mounts have 0777 — copy to /tmp and chmod before loading
mkdir -p /tmp/.ssh
cp -r /root/.ssh/. /tmp/.ssh/
chmod 700 /tmp/.ssh
find /tmp/.ssh -type f -exec chmod 600 {} \;

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

ANSIBLE_CONFIG=/tmp/ansible.cfg ANSIBLE_COLLECTIONS_PATH=/root/.ansible/collections ansible-playbook "$@"
