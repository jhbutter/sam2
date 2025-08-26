#!/bin/bash

# SAM2 Demo 启动脚本
# 同时启动前端和后端服务

set -e

echo "正在启动 SAM2 Demo..."

# 检查是否在正确的目录
if [ ! -f "demo/README.md" ]; then
    echo "错误: 请在 SAM2 项目根目录下运行此脚本"
    exit 1
fi

# 创建日志目录
mkdir -p logs

# 函数：启动后端
start_backend() {
    echo "启动后端服务..."
    cd demo/backend/server/
    
    # 设置环境变量（基于修改后的transcoder.py，不再需要视频编码限制）
    export PYTORCH_ENABLE_MPS_FALLBACK=1
    export APP_ROOT="$(pwd)/../../../"
    export API_URL=http://localhost:7263
    export MODEL_SIZE=base_plus
    export DATA_PATH="$(pwd)/../../data"
    export DEFAULT_VIDEO_PATH=gallery/05_default_juggle.mp4
    
    # 可选的视频编码质量控制（CRF值越低质量越高）
    export VIDEO_ENCODE_CODEC=libx264
    export VIDEO_ENCODE_CRF=23
    export VIDEO_ENCODE_VERBOSE=False
    
    # 启动gunicorn服务器
    gunicorn \
        --worker-class gthread app:app \
        --workers 1 \
        --threads 2 \
        --bind 0.0.0.0:7263 \
        --timeout 60 \
        > ../../../logs/backend.log 2>&1 &
    
    BACKEND_PID=$!
    echo "后端服务已启动 (PID: $BACKEND_PID)"
    echo $BACKEND_PID > ../../../logs/backend.pid
    
    cd ../../../
}

# 函数：启动前端
start_frontend() {
    echo "启动前端服务..."
    cd demo/frontend/
    
    # 检查依赖是否已安装
    if [ ! -d "node_modules" ]; then
        echo "安装前端依赖..."
        yarn install
    fi
    
    # 启动开发服务器
    yarn dev --port 7262 > ../../logs/frontend.log 2>&1 &
    
    FRONTEND_PID=$!
    echo "前端服务已启动 (PID: $FRONTEND_PID)"
    echo $FRONTEND_PID > ../../logs/frontend.pid
    
    cd ../../
}

# 函数：清理进程
cleanup() {
    echo "\n正在停止服务..."
    
    if [ -f "logs/backend.pid" ]; then
        BACKEND_PID=$(cat logs/backend.pid)
        if kill -0 $BACKEND_PID 2>/dev/null; then
            echo "停止后端服务 (PID: $BACKEND_PID)"
            kill $BACKEND_PID
        fi
        rm -f logs/backend.pid
    fi
    
    if [ -f "logs/frontend.pid" ]; then
        FRONTEND_PID=$(cat logs/frontend.pid)
        if kill -0 $FRONTEND_PID 2>/dev/null; then
            echo "停止前端服务 (PID: $FRONTEND_PID)"
            kill $FRONTEND_PID
        fi
        rm -f logs/frontend.pid
    fi
    
    echo "服务已停止"
    exit 0
}

# 设置信号处理
trap cleanup SIGINT SIGTERM

# 检查端口是否被占用
check_port() {
    local port=$1
    if lsof -Pi :$port -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "警告: 端口 $port 已被占用"
        return 1
    fi
    return 0
}

# 检查端口
if ! check_port 7263; then
    echo "后端端口 7263 被占用，请先停止相关服务"
    exit 1
fi

if ! check_port 7262; then
    echo "前端端口 7262 被占用，请先停止相关服务"
    exit 1
fi

# 启动服务
start_backend
sleep 3  # 等待后端启动
start_frontend

echo "\n=== SAM2 Demo 启动完成 ==="
echo "前端地址: http://localhost:7262"
echo "后端地址: http://localhost:7263/graphql"
echo "\n日志文件:"
echo "  后端: logs/backend.log"
echo "  前端: logs/frontend.log"
echo "\n按 Ctrl+C 停止服务"

# 等待用户中断
while true; do
    sleep 1
done