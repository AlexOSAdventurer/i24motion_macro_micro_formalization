ARG UBUNTU_DISTRO="24.04"

FROM ubuntu:${UBUNTU_DISTRO}

ARG UBUNTU_DISTRO
ARG UID=1000
ARG GID=1000
ARG DOCKER_GID=

# Disable interactive prompts during package installation.
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /

# Ubuntu 24.04 ships Python 3.12 as the system python3.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-venv \
        python3-pip \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

# The 24.04 base image ships an "ubuntu" user at UID/GID 1000, which collides with the
# host user on most machines. Remove it, then create a user matching the host UID/GID so
# files written into the bind-mounted workspace keep host ownership.
RUN userdel -r ubuntu 2>/dev/null || true \
    && (getent group ${GID} >/dev/null || groupadd -g ${GID} sim) \
    && useradd -m -s /bin/bash -u ${UID} -g ${GID} sim \
    && if [ -n "${DOCKER_GID}" ]; then \
           (getent group ${DOCKER_GID} >/dev/null || groupadd -g ${DOCKER_GID} docker) \
           && usermod -aG "$(getent group ${DOCKER_GID} | cut -d: -f1)" sim; \
       fi

# PEP 668 marks the system interpreter as externally managed, so install into a venv.
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv ${VIRTUAL_ENV} \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt \
    && chown -R ${UID}:${GID} ${VIRTUAL_ENV}

# The scripts import simulation.py from the parent directory and their siblings by bare
# name; putting both on the path makes them runnable from any working directory.
ENV PYTHONPATH="/sim:/sim/simplified_scenario_tests"
ENV MPLBACKEND=Agg

USER sim
WORKDIR /sim
