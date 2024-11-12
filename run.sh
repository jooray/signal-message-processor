#!/bin/bash

CGROUP_NAME="signal_cli_cgroup"

# Check if the cgroup exists
if [ ! -d "/sys/fs/cgroup/cpu/$CGROUP_NAME" ] || [ ! -d "/sys/fs/cgroup/memory/$CGROUP_NAME" ]; then
    echo "Error: Cgroup '$CGROUP_NAME' does not exist."
    echo "Please initialize it first by running 'initialize_cgroup.sh' as root."
    exit 1
fi

echo "Running signal-logger under cgroup '$CGROUP_NAME'..."
cgexec -g "cpu,memory:$CGROUP_NAME" poetry run python signal_message_processor.py --config config.json --log-level DEBUG
