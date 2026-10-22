#!/bin/bash

# global config
ROOT_DIR="/docker"
APP_DIR="${ROOT_DIR}/$(hostname)"

# move to app dir if the host contains only a single stack
if [ -d "$APP_DIR" ]; then
	# should exist in single-stack hosts
	cd "$APP_DIR"
elif [ -d "$ROOT_DIR" ]; then
	# should exist in both single-stack and multi-stack hosts
	cd "$ROOT_DIR"
fi
