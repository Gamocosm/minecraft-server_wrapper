#!/bin/bash

set -e

mkdir -p minecraft
cd minecraft
python3 ../mcsw.py $@
