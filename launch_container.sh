#!/bin/bash

set -e

DOC_STRING="Run docker containers.

This script launches the formalization docker container."

USAGE_STRING=$(cat <<- END
Usage: $0 [options]

User and group options:

    --user UID:GID      Set host UID and GID for the container (default: current user)
    --docker-gid GID    Set GID of the Docker group (default: $(getent group docker | cut -d: -f3))

Ubuntu distribution:

    --ubuntu-distro DISTRO   Specify ubuntu distro (default: 24.04)

Build options:

    --rebuild           Rebuild the docker image before running

Other commands:

    -h, --help          Show this help message and exit
END
)

UBUNTU_DISTRO=24.04

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_UID=$(id -u)
HOST_GID=$(id -g)
DOCKER_GID=$(getent group docker | cut -d: -f3)

REBUILD=false

OPTS=`getopt -o h --long help,ubuntu-distro:,user:,docker-gid:,rebuild -n 'parse-options' -- "$@"`

eval set -- "$OPTS"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ubuntu-distro )
      UBUNTU_DISTRO="$2";
      shift 2 ;;
    --user )
      IFS=':' read -r HOST_UID HOST_GID <<< "$2"
      shift 2 ;;
    --docker-gid)
      DOCKER_GID="$2"
      shift 2 ;;
    --rebuild )
      REBUILD=true
      shift ;;
    -h | --help )
      echo "$DOC_STRING"
      echo "$USAGE_STRING"
      exit 1
      ;;
    * )
      shift ;;
  esac
done

if ${REBUILD}; then
  echo "Rebuilding image..."
  ${SCRIPT_DIR}/build_container.sh --ubuntu-distro ${UBUNTU_DISTRO} --user ${HOST_UID}:${HOST_GID} --docker-gid ${DOCKER_GID}
fi

echo "Running development container for ubuntu $UBUNTU_DISTRO with user ${HOST_UID}:${HOST_GID}"
docker run \
  -it --rm \
  --name i24-sim-formalization-${UBUNTU_DISTRO} \
  --workdir /sim \
  --net=host \
  --env=DISPLAY=${DISPLAY} \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ${SCRIPT_DIR}:/sim \
  i24-sim-formalization-${UBUNTU_DISTRO} bash
