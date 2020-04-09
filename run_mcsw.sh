#!/usr/bin/env bash

PATH="$HOME/.local/bin:$PATH"

exec flask run --host=0.0.0.0
