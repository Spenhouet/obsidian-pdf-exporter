# Container image of ope: the released package from PyPI, the native libraries WeasyPrint
# needs (Pango, HarfBuzz, fontconfig), pandoc, fonts with emoji, and git with git-lfs for
# redlines. .github/workflows/container.yml builds it for each release.
#
#   docker build --build-arg OPE_VERSION=<version> -t obsidian-pdf-exporter .
#
# Without OPE_VERSION the newest release on PyPI is installed.
FROM python:3.14-slim-trixie

ARG OPE_VERSION=""

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libharfbuzz-subset0 fontconfig \
      fonts-dejavu-core fonts-noto-color-emoji pandoc git git-lfs ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && git lfs install --system \
 # A mounted repository belongs to another user than the one in the container.
 && git config --system --add safe.directory '*'

RUN pip install --no-cache-dir "obsidian-pdf-exporter${OPE_VERSION:+==$OPE_VERSION}" \
 && ope --version

WORKDIR /vault
ENTRYPOINT ["ope"]
CMD ["--help"]
