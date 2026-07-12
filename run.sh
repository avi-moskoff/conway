#!/bin/sh
exec sudo chrt -f 90 taskset -c 3 "$(command -v uv)" run python main.py "$@" 2>&1
