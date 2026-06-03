@echo off
chcp 65001 >nul
echo ==========================================
echo 农业期刊追踪系统 - Windows定时任务配置
echo ==========================================
echo.

REM 检查是否以管理员运行
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 请以管理员身份运行此脚本！
    echo 右键点击脚本，选择"以管理员身份运行"
    pause
    exit /b 1
)

set TASK_NAME=AgriJournalCrawler
echo [1/4] 创建定时任务: %TASK_NAME%

REM 获取当前目录
set SCRIPT_DIR=%~dp0
set PROJECT_DIR=%SCRIPT_DIR%..
set PYTHON_PATH=python

REM 删除旧任务（如果存在）
schtasks /query /tn %TASK_NAME% >nul 2>&1
if %errorlevel% equ 0 (
    echo [信息] 删除旧任务...
    schtasks /delete /tn %TASK_NAME% /f >nul 2>&1
)

REM 创建新任务 - 每天早上8点运行
schtasks /create /tn %TASK_NAME% /tr "%PYTHON_PATH% %PROJECT_DIR%\scripts\fetch_papers.py" /sc daily /st 08:00 /rl highest /f

if %errorlevel% neq 0 (
    echo [错误] 创建任务失败！
    pause
    exit /b 1
)

echo [2/4] 配置任务属性...
REM 设置任务在用户登录时运行，无论是否登录都运行
schtasks /change /tn %TASK_NAME% /it /ru SYSTEM

echo [3/4] 启动任务测试...
schtasks /run /tn %TASK_NAME%

echo [4/4] 显示任务信息...
schtasks /query /tn %TASK_NAME% /fo list

echo.
echo ==========================================
echo 定时任务配置完成！
echo ==========================================
echo.
echo 任务详情:
echo   - 名称: %TASK_NAME%
echo   - 执行: 每天早上 08:00
echo   - 命令: %PYTHON_PATH% %PROJECT_DIR%\scripts\fetch_papers.py
echo   - 工作目录: %PROJECT_DIR%
echo.
echo 可选操作:
echo   1. 手动运行: schtasks /run /tn %TASK_NAME%
echo   2. 修改时间: schtasks /change /tn %TASK_NAME% /st 09:00
echo   3. 删除任务: schtasks /delete /tn %TASK_NAME% /f
echo   4. 查看任务: schtasks /query /tn %TASK_NAME%
echo.
pause
