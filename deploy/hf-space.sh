#!/usr/bin/env bash
# Publishes the committed tree (HEAD, never uncommitted files) to the Hugging
# Face Space. Spaces read their config from a YAML header in README.md, which
# GitHub would render as a table, so the header is added to the uploaded copy only.
# Usage: deploy/hf-space.sh [owner/space]   (needs `hf auth login` first)
set -euo pipefail

SPACE="${1:-utkarshpophli/PaperTrail}"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

git archive HEAD | tar -x -C "$STAGE"
# Spaces build without build args: switch the staged copy to demo mode.
sed -i 's/^ARG DEMO_MODE=0$/ARG DEMO_MODE=1/' "$STAGE/Dockerfile"
{
  cat <<'YAML'
---
title: Paper Trail
emoji: 📄
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Every claim from a paper, traced to an exact quote
---

YAML
  # GitHub's video attachments don't play on the Hub: show the poster, linked to the file.
  git show HEAD:README.md | sed -E 's#^https://github\.com/user-attachments/assets/[0-9a-f-]+$#<a href="assets/demo.mp4"><img src="assets/demo.jpg" alt="Paper Trail demo video" width="100%" /></a>#'
} > "$STAGE/README.md"

hf repos create "$SPACE" --repo-type space --space-sdk docker --exist-ok
hf upload "$SPACE" "$STAGE" . --repo-type space --delete "*" \
  --commit-message "Deploy $(git rev-parse --short HEAD)"
echo "Deployed: https://huggingface.co/spaces/$SPACE"
