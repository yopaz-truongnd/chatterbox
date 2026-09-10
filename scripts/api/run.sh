#!/bin/bash
set -e

# Resolve project root (parent of scripts/api/)
PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$PROJECT_ROOT"

if [ -z "$VIRTUAL_ENV" ]; then
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    elif [ -f "venv/bin/activate" ]; then
        source venv/bin/activate
    fi
fi

# Cấu hình thư mục tạm trong dự án cho API
mkdir -p "$PROJECT_ROOT/tmp/api"
export CHATTERBOX_API_DATA_DIR="${CHATTERBOX_API_DATA_DIR:-$PROJECT_ROOT/tmp/api}"
export PYTHONUNBUFFERED=1
export HF_HUB_CACHE="$PROJECT_ROOT/models"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export PYTHONPATH="src:${PYTHONPATH}"

PYTHON_BIN="python3"
if [ -f "venv/bin/python" ]; then
    PYTHON_BIN="venv/bin/python"
elif [ -f ".venv/bin/python" ]; then
    PYTHON_BIN=".venv/bin/python"
fi

if [ "$1" = "--test" ] || [ "$1" = "test" ]; then
    echo "======================================================================="
    echo "       CHATTERBOX TTS — CHẠY KIỂM THỬ TÍCH HỢP (UNIT TESTS)           "
    echo "======================================================================="
    export CHATTERBOX_IN_PROCESS="${CHATTERBOX_IN_PROCESS:-1}"
    export CHATTERBOX_TEST_DUMMY_INFERENCE="${CHATTERBOX_TEST_DUMMY_INFERENCE:-1}"
    exec "$PYTHON_BIN" -m unittest discover -v tests/
fi

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [ "$1" = "--kill" ] || [ "$1" = "kill" ] || [ "$1" = "--stop" ]; then
    OCCUPIED_PID=$(lsof -ti :"$PORT" 2>/dev/null || true)
    if [ -n "$OCCUPIED_PID" ]; then
        echo "🛑 Đang dừng tiến trình cũ (PID: $OCCUPIED_PID) trên cổng $PORT..."
        kill -9 $OCCUPIED_PID 2>/dev/null || true
        sleep 0.5
        echo "✅ Đã giải phóng cổng $PORT thành công!"
    else
        echo "ℹ️  Cổng $PORT hiện đang không có tiến trình nào chiếm dụng."
    fi
    exit 0
fi

# Kiểm tra nếu cổng đang bị chiếm dụng
OCCUPIED_PID=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$OCCUPIED_PID" ]; then
    echo "⚠️  CẢNH BÁO: Cổng $PORT đang bị chiếm bởi tiến trình PID: $OCCUPIED_PID"
    echo "💡 Bạn có thể giải phóng cổng và chạy lại ngay bằng lệnh:"
    echo "    ./run_chatterbox_api.sh --kill && ./run_chatterbox_api.sh"
    echo "    (hoặc chạy trên cổng khác: PORT=8001 ./run_chatterbox_api.sh)"
    echo
fi

exec "$PYTHON_BIN" -m uvicorn api_app:app --host "$HOST" --port "$PORT"
