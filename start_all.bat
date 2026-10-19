@echo off
rem Start all CST/AST microservices in separate windows (development)
cd /d "%~dp0"

start "language-service :8001" cmd /k "python -m uvicorn language_service.main:app --host 0.0.0.0 --port 8001 --reload"
start "parse-service :8002"     cmd /k "python -m uvicorn parse_service.main:app --host 0.0.0.0 --port 8002 --reload"
timeout /t 2 /nobreak >nul
start "gateway :8000"           cmd /k "python -m uvicorn gateway.main:app --host 0.0.0.0 --port 8000 --reload"

echo.
echo All services launched:
echo   Gateway            http://127.0.0.1:8000   (docs at /docs)
echo   Language service   http://127.0.0.1:8001
echo   Parse service      http://127.0.0.1:8002
