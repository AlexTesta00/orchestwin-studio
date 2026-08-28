FROM docker.io/library/eclipse-temurin:21-jdk-noble@sha256:35685c7e23352983a48882d97cd9875f5284c228db71d1e2476e5e6c1bab1080

RUN groupadd --gid 10001 runner \
    && useradd --create-home --uid 10001 --gid 10001 runner

USER runner
WORKDIR /workspace
ENTRYPOINT []
CMD ["java", "-version"]
