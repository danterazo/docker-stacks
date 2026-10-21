#!/bin/bash
docker exec -t dawarich-db pg_dumpall --clean --if-exists --username=postgres | gzip > "/dumps/postgres-17/dump.sql.gz"
