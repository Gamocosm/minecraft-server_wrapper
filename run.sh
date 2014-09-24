#!/bin/sh

mkdir -p minecraft
cd minecraft
python3 ../minecraft-server_wrapper.py > minecraft-server_wrapper-log.txt 2>&1
