#!/bin/bash
docker compose down
#docker pull louislam/dockge:latest
docker compose pull
docker compose up -d
