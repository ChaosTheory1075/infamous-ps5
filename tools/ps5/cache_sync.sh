#!/bin/bash
if [ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env" ]; then . "$(dirname "${BASH_SOURCE[0]:-$0}")/../local.env"; fi   # local paths / PS5_IP (tools/local.env.example)
# Merge the SPIR-V shader caches: what the console's apps translated while being played plus the
# shipped sets. inFamous 2 and FoB share an engine, so they get the union of both; inFamous 1 its own.
# The merged sets land in ps5\<id>\cache\shaders (what a full install ships) and every file the
# console lacks is uploaded to /data/homebrew/<id>/cache/shaders.   cache_sync.sh
H=ftp://${PS5_IP:?set PS5_IP (tools/local.env)}:2121/data/homebrew
P=${IF_ROOT:-$HOME/inFamous}/ps5
pull() {   # pull <id>: console files missing locally -> local
  local id=$1 n=0
  curl -s --max-time 120 "$H/$id/cache/shaders/" | grep -oE '[0-9a-f]{16}\.spv' | sort -u > /tmp/cs_$id.remote
  ls $P/$id/cache/shaders | sort -u > /tmp/cs_$id.local
  for f in $(comm -23 /tmp/cs_$id.remote /tmp/cs_$id.local); do
    curl -s --max-time 60 -o $P/$id/cache/shaders/$f "$H/$id/cache/shaders/$f" && n=$((n+1))
  done
  echo "$id: pulled $n"
}
share() {  # share <a> <b>: each gets the other's files
  cp -n $P/$1/cache/shaders/*.spv $P/$2/cache/shaders/
  cp -n $P/$2/cache/shaders/*.spv $P/$1/cache/shaders/
}
push() {   # push <id>: local files missing on the console -> console
  local id=$1 n=0
  ls $P/$id/cache/shaders | sort -u > /tmp/cs_$id.local
  for f in $(comm -13 /tmp/cs_$id.remote /tmp/cs_$id.local); do
    curl -s --max-time 60 -T $P/$id/cache/shaders/$f "$H/$id/cache/shaders/$f" && n=$((n+1))
  done
  echo "$id: pushed $n, now $(ls $P/$id/cache/shaders | wc -l) local"
}
for id in PPSA95460 PPSA95461 PPSA95462; do pull $id; done
share PPSA95460 PPSA95461
for id in PPSA95460 PPSA95461 PPSA95462; do push $id; done
