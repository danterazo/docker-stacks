#!/bin/sh
set -eu

address=${1:?A local DNS address is required}
timeout 3 nslookup -type=a id.samskeyti.net "$address" >/dev/null 2>&1
nc -z -w 1 "$address" 53 >/dev/null 2>&1
