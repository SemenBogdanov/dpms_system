#!/bin/sh
set -eu
exec /usr/bin/python3 /usr/local/lib/dpms-local-llm/install_activation.py rollback "$@"
