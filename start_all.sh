#!/usr/bin/env bash
# Start all CST/AST microservices (Linux/macOS development)
cd "$(dirname "$0")"

python3 -m uvicorn language_service.main:app --host 0.0.0.0 --port 8001 --reload &
PIDS="$!"
python3 -m uvicorn parse_service.main:app --host 0.0.0.0 --port 8002 --reload &
PIDS="$PIDS $!"
sleep 1
python3 -m uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload &
PIDS="$PIDS $!"

echo "Services: gateway :8000 | language :8001 | parse :8002  (Ctrl+C to stop)"
trap "kill $PIDS" EXIT
wait
