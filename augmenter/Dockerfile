# Supwave (аугментер). Бинари OpenFlux — ядро, сборщик ссылок oflink и агент ноды
# ofnode — берутся из образа ноды: Go собирать не нужно, а ядро у аугментера то же,
# что на нодах (его он им и заливает). Свой образ ноды: --build-arg NODE_IMAGE=…
ARG NODE_IMAGE=trueheck/openflux-node:latest
FROM ${NODE_IMAGE} AS node

FROM python:3.12-slim
# openssh-client — только для старого пути по SSH (OPENFLUX_DIRECT=on без нод-агентов).
RUN apt-get update && apt-get install -y --no-install-recommends openssh-client \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py node-install.sh ./
COPY --from=node /usr/local/bin/openflux /app/openflux-node-v1.6.0
COPY --from=node /usr/local/bin/ofnode /app/ofnode
COPY --from=node /usr/local/bin/oflink /app/oflink
RUN chmod 0755 /app/oflink /app/node-install.sh /app/openflux-node-v1.6.0 /app/ofnode
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
