#!/bin/sh
set -eu

nc -z -w 1 127.0.0.1 80
nc -z -w 1 127.0.0.1 443
