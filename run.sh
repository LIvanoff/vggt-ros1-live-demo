#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)"
step=${1:-build}
case "$step" in
  build)
    docker compose build ros
    docker compose up -d ros
    docker compose exec -T ros bash -lc 'source /opt/ros/noetic/setup.bash && cd /demo/catkin_ws && catkin_make'
    ;;
  roscore) docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && roscore' ;;
  node)
    frames=${2:-2}
    [[ "$frames" =~ ^[2-8]$ ]] || { echo 'Frames must be 2..8' >&2; exit 2; }
    docker compose exec ros bash -lc "source /opt/ros/noetic/setup.bash && source /demo/catkin_ws/devel/setup.bash && roslaunch vggt_scene scene.launch frames:=$frames"
    ;;
  bag) docker compose exec ros bash -lc 'source /opt/ros/noetic/setup.bash && rosbag play --clock --pause /demo/data/nuplan_front_2hz.bag' ;;
  worker) .venv/bin/python worker/watch.py --device cpu --precision int8 --min-free-ram-gib 3 --once ;;
  worker-jetson) docker compose --profile jetson run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp worker ;;
  stop) docker compose --profile jetson down ;;
  *) echo 'Usage: bash run.sh {build|roscore|node [2..8]|bag|worker|worker-jetson|stop}' >&2; exit 2 ;;
esac
