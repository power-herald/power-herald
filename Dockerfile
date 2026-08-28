FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 power-herald

COPY pyproject.toml README.md LICENSE ./
COPY power_herald ./power_herald
RUN pip install --no-cache-dir .

COPY locale.yaml ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint

RUN chmod 755 /usr/local/bin/docker-entrypoint \
    && mkdir /docker-init.d \
    && chown -R power-herald:power-herald /app /docker-init.d
USER power-herald

EXPOSE 8080 8081

ENTRYPOINT ["docker-entrypoint"]
CMD ["ph-server"]