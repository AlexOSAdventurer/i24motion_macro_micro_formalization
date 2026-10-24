#!/bin/bash

set -e

DOC_STRING="Build docker images.

This script builds the docker image for evaluating the stack."

USAGE_STRING=$(cat <<- END
Usage: $0 [options]

User and group options:

    --user UID:GID       Set host UID and GID for the container (default: current user)
    --docker-gid GID     Set GID of the Docker group (default: $(getent group docker | cut -d: -f3))

Ubuntu distribution:

    --ubuntu-distro DISTRO   Specify ubuntu distro (default: 24.04).

Build options:

    --force-rebuild      Force rebuild images with no cache

Other commands:

    -h, --help           Show this help message and exit
END
)

UBUNTU_DISTRO=24.04

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_UID=$(id -u)
HOST_GID=$(id -g)
DOCKER_GID=$(getent group docker | cut -d: -f3)

FORCE_REBUILD=

OPTS=`getopt -o h --long help,ubuntu-distro:,user:,docker-gid:,force-rebuild -n 'parse-options' -- "$@"`

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
    --force-rebuild )
      FORCE_REBUILD=true
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

echo "Building development image i24-sim-formalization-${UBUNTU_DISTRO} with user ${HOST_UID}:${HOST_GID}"
docker build ${FORCE_REBUILD:+--no-cache} \
  --build-arg UBUNTU_DISTRO=${UBUNTU_DISTRO} \
  --build-arg UID=${HOST_UID} \
  --build-arg GID=${HOST_GID} \
  --build-arg DOCKER_GID=${DOCKER_GID} \
  -t i24-sim-formalization-${UBUNTU_DISTRO} \
  -f ${SCRIPT_DIR}/i24_sim_formalization.Dockerfile ${SCRIPT_DIR}
