#!/bin/bash

echo "=========================================="
echo "农业期刊追踪系统 - macOS 定时任务配置"
echo "=========================================="
echo ""

# 获取当前脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_PATH=$(which python3)

if [ -z "$PYTHON_PATH" ]; then
    echo "[错误] 未找到 python3，请确保已安装 Python！"
    exit 1
fi

echo "[1/3] 准备配置 Cron 任务..."
CRON_JOB="0 8 * * * cd \"$PROJECT_DIR\" && $PYTHON_PATH scripts/fetch_papers.py >> \"$PROJECT_DIR/scripts/crawler.log\" 2>&1"

echo "[2/3] 更新 crontab..."
# 检查是否已存在该任务，如果存在则先删除旧任务
(crontab -l 2>/dev/null | grep -v "fetch_papers.py") | crontab -

# 添加新任务
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo "[3/3] 验证任务..."
crontab -l | grep "fetch_papers.py"

echo ""
echo "=========================================="
echo "定时任务配置完成！"
echo "=========================================="
echo ""
echo "任务详情:"
echo "  - 执行时间: 每天早上 08:00"
echo "  - 执行命令: cd $PROJECT_DIR && $PYTHON_PATH scripts/fetch_papers.py"
echo "  - 日志文件: $PROJECT_DIR/scripts/crawler.log"
echo ""
echo "可选操作:"
echo "  1. 查看所有任务: crontab -l"
echo "  2. 编辑任务: crontab -e"
echo "  3. 删除所有任务: crontab -r (注意：会删除当前用户的所有cron任务)"
echo ""
