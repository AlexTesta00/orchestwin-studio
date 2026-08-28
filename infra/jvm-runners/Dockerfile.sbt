FROM docker.io/library/eclipse-temurin:26-jdk-noble@sha256:091b6640864939942cd9d7ddd16576f31112d5a56a595b566ce561d1c0e07c6b

ARG SBT_VERSION=1.12.14
ARG SBT_SHA256=cd17daae220ff264faa4251334522444518584f0eb2ee82da01523a9b9002b7e

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl \
    && curl --fail --location --silent --show-error \
       "https://github.com/sbt/sbt/releases/download/v${SBT_VERSION}/sbt-${SBT_VERSION}.tgz" \
       --output /tmp/sbt.tgz \
    && echo "${SBT_SHA256}  /tmp/sbt.tgz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/sbt.tgz --directory /opt \
    && ln --symbolic /opt/sbt/bin/sbt /usr/local/bin/sbt \
    && rm --force /tmp/sbt.tgz \
    && rm --recursive --force /var/lib/apt/lists/*

USER 65532:65532
WORKDIR /workspace
ENTRYPOINT []
CMD ["sbt", "--script-version"]
