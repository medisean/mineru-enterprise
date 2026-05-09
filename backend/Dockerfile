ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

WORKDIR /app

ARG APT_MIRROR=
ARG PIP_INDEX_URL=
ARG PIP_EXTRA_INDEX_URL=

# System dependencies for MinerU and LDAP
RUN if [ -n "$APT_MIRROR" ]; then \
        if [ -f /etc/apt/sources.list.d/debian.sources ]; then sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list.d/debian.sources; fi; \
        if [ -f /etc/apt/sources.list ]; then sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list; fi; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libmagic1 libgl1 libglib2.0-0 \
    libldap2-dev libsasl2-dev \
    curl wget \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ]; then python -m pip config set global.index-url "$PIP_INDEX_URL"; fi \
    && if [ -n "$PIP_EXTRA_INDEX_URL" ]; then python -m pip config set global.extra-index-url "$PIP_EXTRA_INDEX_URL"; fi \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
