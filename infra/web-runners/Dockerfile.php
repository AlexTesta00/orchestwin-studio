FROM docker.io/library/composer:2.10.2@sha256:4d71c3c2109c61d5415544264b59ad4087e4c5b7244481723664138fd36d5040 AS composer_source
FROM docker.io/library/php:8.4.24-cli-bookworm@sha256:6003a0607eea6dc61d04723d3e60347c8481ffb2f09dbf85bf427b9ce0c25629

COPY --from=composer_source /usr/bin/composer /usr/local/bin/composer
COPY infra/web-runners/bin/php-lint.php /opt/orchestwin/bin/php-lint.php

RUN useradd --create-home --uid 10001 runner
USER runner
WORKDIR /workspace
ENTRYPOINT []
CMD ["php", "--version"]
