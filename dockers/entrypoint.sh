#!/bin/bash
set -e

# Create the log directory if it is not there, and hand it to appuser
mkdir -p /app/logs
chown appuser:appuser /app/logs

# Drop to appuser and run the command that was passed
exec gosu appuser "$@"
