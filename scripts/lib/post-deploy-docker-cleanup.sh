#!/usr/bin/env bash
# Remove reproducible Docker artifacts after a verified release.
if ! docker builder prune --all --force; then
  echo 'Warning: could not clean unused Docker build cache.' >&2
fi
if ! docker image prune --force; then
  echo 'Warning: could not clean dangling Docker images.' >&2
fi
