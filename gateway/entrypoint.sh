#!/bin/sh
# Sobe o LiteLLM e provisiona as chaves virtuais sem passo manual.
# O healthcheck do serviço só passa depois do provisionamento (marcador em /tmp).
set -e
rm -f /tmp/provisioned
litellm --config /gateway/config.yaml --port 4000 &
LITELLM_PID=$!
python /gateway/provision.py
touch /tmp/provisioned
wait $LITELLM_PID
