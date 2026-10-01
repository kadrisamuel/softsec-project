#! /bin/bash

echo "Building docker images..."
if [[ "$(uname)" == "Darwin" ]]; then
    docker-compose build --no-cache
else
    docker compose buld --no-cache
fi

echo "Exporting docker images..."
mkdir tmp
docker save softsec-project-server:latest > tmp/server.tar
docker save mariadb@sha256:805c8e104bd563d5bfa24fadd3f31cd419ea859cb5277f32b5dbf2db714f9ed1 > tmp/db.tar

echo "Generating SBOMs..."
syft scan tmp/server.tar -o cyclonedx-json=sboms/server.cdx.json
syft scan tmp/db.tar -o cyclonedx-json=sboms/db.cdx.json

echo "Cleaning up..."
rm -r tmp
