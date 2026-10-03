#! /bin/bash
set -e

echo "Building docker images..."
if [[ "$(uname)" == "Darwin" ]]; then
    docker-compose build --no-cache
else
    docker compose build --no-cache
fi

echo "Exporting docker images..."
if [ -d "tmp" ]; then
    echo "Cleaning existing image exports..."
    rm -r tmp
fi
mkdir tmp
docker save softsec-project-server:latest > tmp/server.tar
docker save $(yq '.services.db.image' docker-compose.yml) > tmp/db.tar

echo "Generating SBOMs..."
SYFT_FORMAT_PRETTY=1 syft scan tmp/server.tar -o cyclonedx-json=sboms/server.cdx.json
SYFT_FORMAT_PRETTY=1 syft scan tmp/db.tar -o cyclonedx-json=sboms/db.cdx.json

echo "Cleaning up..."
rm -r tmp
