ARG API_BASE_IMAGE=ubuntu:22.04
FROM ${API_BASE_IMAGE}

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

ARG APT_MIRROR=
ARG API_UBUNTU_APT_MIRROR=
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=

# System dependencies for MinerU and LDAP
RUN mirror="${API_UBUNTU_APT_MIRROR:-$APT_MIRROR}"; \
    if [ -n "$mirror" ]; then \
        if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then sed -i "s|http://archive.ubuntu.com/ubuntu|${mirror}|g; s|http://security.ubuntu.com/ubuntu|${mirror}|g" /etc/apt/sources.list.d/ubuntu.sources; fi; \
        if [ -f /etc/apt/sources.list ]; then sed -i "s|http://archive.ubuntu.com/ubuntu|${mirror}|g; s|http://security.ubuntu.com/ubuntu|${mirror}|g" /etc/apt/sources.list; fi; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libmagic1 libgl1 libglib2.0-0 \
    libldap2-dev libsasl2-dev \
    curl wget python3 python3-venv python3-dev python3-pip \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && python3 -m venv /opt/venv \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then python3 -m pip config set global.index-url "$PIP_INDEX_URL"; fi \
    && if [ -n "$PIP_EXTRA_INDEX_URL" ]; then python3 -m pip config set global.extra-index-url "$PIP_EXTRA_INDEX_URL"; fi \
    && python3 -m pip install --upgrade pip setuptools wheel \
    && python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
