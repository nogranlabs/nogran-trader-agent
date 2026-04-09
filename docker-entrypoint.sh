#!/usr/bin/env sh
# nogran.trader.agent entrypoint dispatcher.
# Dispatches based on the first argument:
#   agent      -> python src/main.py
#   dashboard  -> streamlit run dashboard/app.py
#   shell      -> drop into /bin/sh
#   *          -> exec the literal command
set -e

CMD="${1:-dashboard}"
shift || true

case "$CMD" in
  agent)
    exec python src/main.py "$@"
    ;;
  dashboard)
    exec streamlit run dashboard/app.py \
      --server.address=0.0.0.0 \
      --server.port=8501 \
      --server.headless=true \
      --browser.gatherUsageStats=false \
      "$@"
    ;;
  shell)
    exec /bin/sh
    ;;
  *)
    exec "$CMD" "$@"
    ;;
esac
