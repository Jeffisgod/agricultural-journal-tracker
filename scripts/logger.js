import fs from 'fs';
import path from 'path';

const LOG_FILE = path.resolve('scripts/crawler.log');
const STATUS_FILE = path.resolve('scripts/crawler-status.json');

/**
 * 记录爬虫日志
 * @param {string} level - 日志级别: info, success, error, warning
 * @param {string} message - 日志消息
 */
export function log(level, message) {
  const timestamp = new Date().toLocaleString('zh-CN');
  const logEntry = `[${timestamp}] [${level.toUpperCase()}] ${message}\n`;
  
  // 输出到控制台
  console.log(logEntry.trim());
  
  // 写入日志文件（追加模式）
  fs.appendFileSync(LOG_FILE, logEntry, 'utf-8');
}

/**
 * 更新爬虫状态
 * @param {Object} status - 状态对象
 */
export function updateStatus(status) {
  const currentStatus = readStatus();
  const newStatus = {
    ...currentStatus,
    ...status,
    lastUpdate: new Date().toISOString()
  };
  fs.writeFileSync(STATUS_FILE, JSON.stringify(newStatus, null, 2), 'utf-8');
}

/**
 * 读取爬虫状态
 * @returns {Object} 状态对象
 */
export function readStatus() {
  try {
    if (fs.existsSync(STATUS_FILE)) {
      return JSON.parse(fs.readFileSync(STATUS_FILE, 'utf-8'));
    }
  } catch (e) {
    // 忽略读取错误
  }
  return {
    lastRun: null,
    lastSuccess: null,
    totalPapers: 0,
    journalsCount: 0,
    isRunning: false,
    nextScheduledRun: null
  };
}

/**
 * 获取日志内容（最近的N行）
 * @param {number} lines - 行数
 * @returns {string} 日志内容
 */
export function getRecentLogs(lines = 50) {
  try {
    if (fs.existsSync(LOG_FILE)) {
      const content = fs.readFileSync(LOG_FILE, 'utf-8');
      return content.split('\n').filter(l => l.trim()).slice(-lines).join('\n');
    }
  } catch (e) {
    return '暂无日志';
  }
  return '暂无日志';
}

/**
 * 清除旧日志
 */
export function clearOldLogs() {
  try {
    if (fs.existsSync(LOG_FILE)) {
      const content = fs.readFileSync(LOG_FILE, 'utf-8');
      const lines = content.split('\n').filter(l => l.trim());
      // 只保留最近1000行
      if (lines.length > 1000) {
        const newContent = lines.slice(-1000).join('\n') + '\n';
        fs.writeFileSync(LOG_FILE, newContent, 'utf-8');
      }
    }
  } catch (e) {
    // 忽略错误
  }
}
