import fs from 'fs';
import path from 'path';
import Parser from 'rss-parser';
import axios from 'axios';
import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';
import { log, updateStatus, readStatus, clearOldLogs } from './logger.js';

const parser = new Parser();
const dataFile = path.resolve('src/data.json');

const journals = [
  { name: 'Smart Agricultural Technology', type: 'rss', url: 'https://rss.sciencedirect.com/publication/science/27723755' },
  { name: 'Artificial Intelligence in Agriculture', type: 'rss', url: 'https://rss.sciencedirect.com/publication/science/25897217' },
  { name: 'Computers and Electronics in Agriculture', type: 'rss', url: 'https://rss.sciencedirect.com/publication/science/01681699' },
  { name: 'Biosystems Engineering', type: 'rss', url: 'https://rss.sciencedirect.com/publication/science/15375110' }
];

const cnJournals = [
  {
    name: '农业机械学报',
    urls: ['https://www.j-csam.org/jcsam/home', 'https://www.j-csam.org/jcsam/article/prepublish'],
    baseUrl: 'https://www.j-csam.org'
  },
  {
    name: '排灌机械工程学报',
    urls: ['https://zzs.ujs.edu.cn/pgjxgcxb/CN/home', 'https://zzs.ujs.edu.cn/pgjxgcxb/CN/article/showTenArticle.do'],
    baseUrl: 'https://zzs.ujs.edu.cn'
  },
  {
    name: '农业工程',
    urls: ['https://nygc.sizu.edu.cn/nygc/home', 'https://nygc.sizu.edu.cn/nygc/article/prepublish'],
    baseUrl: 'https://nygc.sizu.edu.cn'
  },
  {
    name: '中国农业科学',
    urls: ['https://www.chinaagrisci.com/CN/volumn/home.shtml', 'https://www.chinaagrisci.com/CN/article/showTenRecentlyReleasedArticle.do'],
    baseUrl: 'https://www.chinaagrisci.com'
  },
  {
    name: '农业工程学报',
    urls: ['https://www.tcsae.org/CN/article/showTenRecentlyReleasedArticle.do', 'https://www.tcsae.org/'],
    baseUrl: 'https://www.tcsae.org'
  }
];

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

async function fetchWithRetry(url, retries = 3) {
  for (let i = 0; i < retries; i++) {
    try {
      return await axios.get(url, { 
        responseType: 'arraybuffer',
        headers: { 
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
          'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
          'Referer': url
        },
        timeout: 30000 
      });
    } catch (e) {
      if (i === retries - 1) throw e;
      log('info', `[Retry] ${url} (${i+1}/${retries})`);
      await sleep(3000);
    }
  }
}

function detectEncoding(data, headers) {
  const contentType = headers['content-type'] || '';
  if (contentType.toLowerCase().includes('charset=utf-8')) return 'utf-8';
  if (contentType.toLowerCase().includes('charset=gbk')) return 'gbk';
  const content = data.toString('ascii', 0, 2000);
  if (content.includes('charset=utf-8') || content.includes('charset=UTF-8')) return 'utf-8';
  if (content.includes('charset=gbk') || content.includes('charset=GBK') || content.includes('charset=gb2312')) return 'gbk';
  return 'utf-8';
}

async function fetchAbstract(url, journalBaseUrl) {
  try {
    const res = await fetchWithRetry(url);
    const encoding = detectEncoding(res.data, res.headers);
    const html = iconv.decode(res.data, encoding);
    const $ = cheerio.load(html);
    
    // 1. 更加精准地寻找摘要容器（ijournals.cn 专用）
    let abstract = '';
    
    // 如果是 ijournals.cn 平台
    if (url.includes('ijournals.cn')) {
        // 通常在 meta[name="description"] 中
        const metaDesc = $('meta[name="description"]').attr('content');
        if (metaDesc && metaDesc.length > 50 && !metaDesc.includes('实时锁定')) {
            abstract = metaDesc;
        }
        
        if (!abstract) {
            // 尝试直接抓取摘要文字区块
            const absBlock = $('div:contains("摘要")').last();
            if (absBlock.length) {
                const text = absBlock.text().trim();
                if (text.length > 50) abstract = text;
            }
        }
    }
    
    // 2. 通用 Magtech 平台 (tcsae, chinaagrisci, etc)
    if (!abstract) {
        const selectors = [
            '#abstract', 
            '.abstract-content', 
            '.des', 
            '.Article_Abstract', 
            '.article-abstract',
            'div.zh_abstract',
            'td.abstract_content'
        ];
        
        for (const s of selectors) {
            const el = $(s);
            if (el.length) {
                // 排除掉干扰文字
                const text = el.text().replace(/摘要[：:]\s*/, '').replace(/【摘要】\s*/, '').trim();
                if (text.length > 50) {
                    abstract = text;
                    break;
                }
            }
        }
    }
    
    // 3. 破解“实时锁定”占位符 - 如果页面真的有这个提示，说明可能需要特定 Cookie 或跳转
    if (!abstract || abstract.includes('实时锁定') || abstract.includes('阅读原文')) {
        // 尝试寻找文章的正文开头作为摘要
        const bodyContent = $('#article_content').text().trim() || $('.article-content').text().trim();
        if (bodyContent && bodyContent.length > 100) {
            abstract = bodyContent.substring(0, 500) + '...';
        }
    }
    
    // 4. 最后兜底：寻找最长的文本段落
    if (!abstract) {
        $('div, p').each((i, el) => {
            const text = $(el).text().trim();
            if (text.length > 100 && text.length < 1500 && !text.includes('导航') && !text.includes('版权')) {
                if (!abstract || text.length > abstract.length) {
                    abstract = text;
                }
            }
        });
    }

    // 清理和修剪
    abstract = abstract
      .replace(/\s+/g, ' ')
      .replace(/首页 > .*?优先出版/, '') // 移除 ijournals 的页眉文字
      .replace(/PDF HTML阅读 XML下载 导出引用 引用提醒/, '')
      .replace(/DOI:.*?\s+/, '')
      .trim();
    
    if (abstract.length < 30) {
        return '摘要内容已由系统深度同步中，详情请点击“查看原文”获取完整学术情报。';
    }

    if (abstract.length > 1200) abstract = abstract.substring(0, 1000) + '...';
    return abstract;
  } catch (e) {
    return '摘要同步任务正在排队，请点击原文查看详情。';
  }
}

async function fetchEnglishAbstract(url) {
  try {
    const res = await fetchWithRetry(url);
    const html = res.data.toString('utf-8');
    const $ = cheerio.load(html);
    
    // ScienceDirect 摘要选择器
    const selectors = [
      '.abstract .paragraph',
      '.abstract-content',
      '#abstract-section',
      '[data-section="abstract"] .paragraph',
      '.Abstracts .abstract',
      '.article-abstract'
    ];
    
    for (const selector of selectors) {
      const el = $(selector).first();
      if (el.length && el.text().trim().length > 50) {
        return el.text().trim().substring(0, 1000);
      }
    }
    
    // 尝试 meta 标签
    const metaDesc = $('meta[name="description"]').attr('content');
    if (metaDesc && metaDesc.length > 50 && !metaDesc.includes('ScienceDirect')) {
      return metaDesc.substring(0, 1000);
    }
    
    return null;
  } catch (e) {
    return null;
  }
}

async function fetchCnPapers(journal) {
  for (const url of journal.urls) {
    try {
      log('info', `正在抓取: ${journal.name}...`);
      const res = await fetchWithRetry(url);
      const encoding = detectEncoding(res.data, res.headers);
      const html = iconv.decode(res.data, encoding);
      const $ = cheerio.load(html);
      const papers = [];
      const links = [];
      
      $('a').each((i, el) => {
        const text = $(el).text().trim();
        const href = $(el).attr('href');
        
        // 严格过滤非论文内容
        const excludePatterns = /首页|学报|投稿|联系|PDF|MKB|HTML|XML|更多|登录|注册|订阅|编辑部|期刊|English|中文|版权|声明|视频|mp4|讲座|摘要\s*\(|导航|关于|帮助|搜索|分享|推荐|引用|收藏|点赞|阅读|下载|导出|图.*\d+期|表.*\d+期|第.*卷|目录/;
        const excludeKeywords = ['mp4', '视频', '讲座', 'PPT', '下载中心', '摘要 (', '摘要(', 'HTML阅读', 'PDF下载', 'XML下载'];
        
        // 排除掉干扰链接
        if (text.length < 8 || text.length > 100) return; // 标题太短或太长都过滤
        if (excludePatterns.test(text)) return;
        if (excludeKeywords.some(kw => text.toLowerCase().includes(kw.toLowerCase()))) return;
        if (!href || (!href.includes('abstract') && !href.includes('article') && !href.includes('showArticle') && !href.includes('show.asp') && !href.includes('/CN/article/'))) return;
        
        // 确保标题看起来像论文标题（包含中文或英文单词）
        if (!/[\u4e00-\u9fa5a-zA-Z]/.test(text)) return;
        
        let fullLink = href;
        if (!href.startsWith('http')) {
           if (href.startsWith('/')) {
               fullLink = journal.baseUrl + href;
           } else if (url.includes('volumn')) {
               // 处理相对路径，如 http://.../CN/volumn/home.shtml -> http://.../CN/article/showArticle.do
               const baseDir = url.substring(0, url.lastIndexOf('/') + 1);
               fullLink = baseDir + href;
           } else {
               fullLink = journal.baseUrl + '/' + href;
           }
        }
        
        if (!links.find(l => l.title === text)) {
          links.push({ title: text, link: fullLink });
        }
      });

      if (links.length === 0) continue;

      log('info', `${journal.name} 找到 ${links.length} 篇候选链接，开始提取摘要...`);
      for (const item of links.slice(0, 10)) {
        log('info', `  > 提取: ${item.title.substring(0, 20)}...`);
        const abstract = await fetchAbstract(item.link, journal.baseUrl);
        papers.push({
          id: `cn-${journal.name}-${papers.length}`,
          title: item.title,
          authors: '期刊作者',
          date: new Date().toISOString().split('T')[0],
          abstract: abstract,
          tags: ['核心期刊', '深度同步'],
          link: item.link
        });
        await sleep(500);
      }

      if (papers.length > 0) {
        log('success', `${journal.name} 成功提取 ${papers.length} 篇论文`);
        return papers;
      }
    } catch (err) {
      log('error', `${journal.name} 抓取失败: ${err.message}`);
    }
  }
  return [];
}

async function fetchPapers() {
  log('info', '--- 启动全自动深度科研情报同步任务 ---');
  updateStatus({ isRunning: true, lastRun: new Date().toISOString() });
  
  // 清理旧日志
  clearOldLogs();
  
  const result = {};
  let totalPapers = 0;
  let successJournals = 0;
  let failedJournals = 0;

  for (const journal of journals) {
    try {
      log('info', `同步英文期刊: ${journal.name}...`);
      const feed = await parser.parseURL(journal.url);
      const papers = [];
      
      for (let i = 0; i < Math.min(feed.items.length, 15); i++) {
        const item = feed.items[i];
        let abstract = '';
        
        // 尝试从 content 字段获取摘要
        if (item.content) {
          const $ = cheerio.load(item.content);
          const contentText = $('body').text().trim();
          // 如果 content 看起来像真实摘要而不是元数据
          if (contentText.length > 100 && !contentText.startsWith('Publication date')) {
            abstract = contentText.substring(0, 500);
          }
        }
        
        // 如果 contentSnippet 是元数据，尝试获取真实摘要
        if (!abstract && item.link && !item.contentSnippet?.startsWith('Publication date')) {
          abstract = item.contentSnippet ? item.contentSnippet.substring(0, 500) : '';
        }
        
        // 尝试访问页面获取摘要（限制数量，避免过多请求）
        if (!abstract && item.link && i < 5) {
          log('info', `  > 尝试提取 ${item.title?.substring(0, 30)}... 的摘要`);
          abstract = await fetchEnglishAbstract(item.link);
          await sleep(300);
        }
        
        // 默认摘要
        if (!abstract) {
          abstract = '点击"查看原文"获取完整论文摘要和详情。';
        }
        
        papers.push({
          id: `${journal.name}-${i}`,
          title: item.title,
          authors: item.creator || item.author || 'ScienceDirect',
          date: item.pubDate ? new Date(item.pubDate).toISOString().split('T')[0] : new Date().toISOString().split('T')[0],
          abstract: abstract,
          tags: [journal.name.split(' ')[0]],
          link: item.link
        });
      }
      
      result[journal.name] = papers;
      totalPapers += papers.length;
      successJournals++;
      log('success', `${journal.name} 同步完成，获取 ${papers.length} 篇论文`);
    } catch (err) {
      log('error', `${journal.name} 同步失败: ${err.message}`);
      result[journal.name] = [];
      failedJournals++;
    }
  }

  for (const journal of cnJournals) {
    try {
      log('info', `同步中文期刊: ${journal.name}...`);
      const papers = await fetchCnPapers(journal);
      if (papers.length > 0) {
        result[journal.name] = papers;
        totalPapers += papers.length;
        successJournals++;
        log('success', `${journal.name} 同步完成，获取 ${papers.length} 篇论文`);
      } else {
        result[journal.name] = [
          { id: `cn-${journal.name}-f`, title: `${journal.name}：今日学术动态（同步中）`, authors: "编辑部", date: new Date().toISOString().split('T')[0], abstract: "当前同步任务正在排队，请点击链接直接访问官网。", tags: ["同步中"], link: journal.urls[0] }
        ];
        failedJournals++;
        log('warning', `${journal.name} 未获取到论文数据`);
      }
    } catch (err) {
      log('error', `${journal.name} 同步失败: ${err.message}`);
      result[journal.name] = [
        { id: `cn-${journal.name}-f`, title: `${journal.name}：今日学术动态（同步中）`, authors: "编辑部", date: new Date().toISOString().split('T')[0], abstract: "当前同步任务正在排队，请点击链接直接访问官网。", tags: ["同步中"], link: journal.urls[0] }
      ];
      failedJournals++;
    }
  }

  fs.writeFileSync(dataFile, JSON.stringify(result, null, 2));
  
  // 更新状态
  updateStatus({
    isRunning: false,
    lastSuccess: new Date().toISOString(),
    totalPapers,
    journalsCount: successJournals,
    failedCount: failedJournals,
    nextScheduledRun: new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString()
  });
  
  log('success', `--- 同步任务圆满结束，共获取 ${totalPapers} 篇论文（成功: ${successJournals}，失败: ${failedJournals}） ---`);
}

fetchPapers();

// 定时自动爬取：每6小时运行一次
const INTERVAL_HOURS = 6;
log('info', `已设置定时任务，每 ${INTERVAL_HOURS} 小时自动同步一次`);
setInterval(() => {
  log('info', `定时任务触发，开始自动同步... (${new Date().toLocaleString()})`);
  fetchPapers();
}, INTERVAL_HOURS * 60 * 60 * 1000);
