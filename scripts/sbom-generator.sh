#! /bin/bash
set -e

echo "Building docker images..."
if [[ "$(uname)" == "Darwin" ]]; then
    docker-compose build --no-cache
else
    docker compose build --no-cache
fi

echo "Exporting docker images..."
docker save softsec-project-server:latest > server-image.tar

echo "Generating SBOMs..."
if [[ "$(uname)" == "Darwin" ]]; then
    db_image=$(docker-compose config --images db)
else
    db_image=$(docker compose config --images db)
fi
SYFT_FORMAT_PRETTY=1 syft scan server-image.tar -o cyclonedx-json=sboms/server.cdx.json
SYFT_FORMAT_PRETTY=1 syft scan "registry:$db_image" -o cyclonedx-json=sboms/db.cdx.json

echo "Cleaning up..."
rm server-image.tar
