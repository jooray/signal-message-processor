#!/bin/bash

# Cgroup name
CGROUP_NAME="signal_cli_cgroup"

# CPU and memory limits
CPU_QUOTA="25000"  # 25% of one CPU core
CPU_PERIOD="100000"  # Default period (100ms)
MEMORY_LIMIT="750M"  # 750MB

echo "Initializing cgroup '$CGROUP_NAME'..."

# Create CPU cgroup if it doesn't exist
if [ ! -d "/sys/fs/cgroup/cpu/$CGROUP_NAME" ]; then
    echo "Creating CPU cgroup..."
    sudo cgcreate -g "cpu:$CGROUP_NAME"
else
    echo "CPU cgroup already exists."
fi

# Set CPU limits
echo "Setting CPU quota to $CPU_QUOTA..."
echo "$CPU_QUOTA" | sudo tee "/sys/fs/cgroup/cpu/$CGROUP_NAME/cpu.cfs_quota_us" > /dev/null
echo "$CPU_PERIOD" | sudo tee "/sys/fs/cgroup/cpu/$CGROUP_NAME/cpu.cfs_period_us" > /dev/null

# Create memory cgroup if it doesn't exist
if [ ! -d "/sys/fs/cgroup/memory/$CGROUP_NAME" ]; then
    echo "Creating memory cgroup..."
    sudo cgcreate -g "memory:$CGROUP_NAME"
else
    echo "Memory cgroup already exists."
fi

# Set memory limits
echo "Setting memory limit to $MEMORY_LIMIT..."
echo "$MEMORY_LIMIT" | sudo tee "/sys/fs/cgroup/memory/$CGROUP_NAME/memory.limit_in_bytes" > /dev/null

echo "Cgroup '$CGROUP_NAME' has been initialized with CPU and memory limits."
