#!/usr/bin/env sh
# Build the .difypkg bundle with the official Dify plugin CLI.
# Install the CLI first:  pip install dify-plugin-cli
set -e

# This repository root IS the plugin (manifest.yaml sits next to this script).
dify plugin package . -o stream-proxy.difypkg
echo "Built: stream-proxy.difypkg"
