FROM docker.io/library/eclipse-temurin:21-jdk-noble@sha256:35685c7e23352983a48882d97cd9875f5284c228db71d1e2476e5e6c1bab1080

ADD --checksum=sha256:cd17daae220ff264faa4251334522444518584f0eb2ee82da01523a9b9002b7e https://github.com/sbt/sbt/releases/download/v1.12.14/sbt-1.12.14.tgz /tmp/sbt.tgz

RUN echo "cd17daae220ff264faa4251334522444518584f0eb2ee82da01523a9b9002b7e  /tmp/sbt.tgz" | sha256sum --check --strict \
    && tar --extract --gzip --file /tmp/sbt.tgz --directory /opt \
    && ln --symbolic /opt/sbt/bin/sbt /usr/local/bin/sbt \
    && rm --force /tmp/sbt.tgz

USER 65532:65532
WORKDIR /workspace
ENTRYPOINT []
CMD ["sbt", "--script-version"]
