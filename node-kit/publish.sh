#!/bin/sh
# Собрать образ ноды из бинарей этой папки и выложить в Docker Hub:
#   sh publish.sh <логин>/openflux-node
# Один раз до этого: docker login -u <логин> (пароль — access token Docker Hub с правами
# Read & Write). Теги: :latest (его берёт compose нод) и :<sha256 ofnode, 12 знаков> —
# неизменный, для отката. Ядро в образе только стартовое: актуальное аугментер
# заливает на ноду сам (PUT /core), так что образ пересобирать — только при новом ofnode.
set -eu
repo=${1:?"нужно: sh publish.sh <логин>/openflux-node"}
cd "$(dirname "$0")"
for f in Dockerfile.bin ofnode openflux oflink; do
	[ -f "$f" ] || { echo "нет $f рядом со скриптом" >&2; exit 1; }
done
tag=$( (sha256sum ofnode 2>/dev/null || shasum -a 256 ofnode) | cut -c1-12)
docker build --pull --platform linux/amd64 -f Dockerfile.bin -t "$repo:$tag" -t "$repo:latest" .
docker push "$repo:$tag"
docker push "$repo:latest"
echo "готово: $repo:latest = $repo:$tag"
echo "в .env аугментера: OPENFLUX_NODE_IMAGE=$repo:latest"
