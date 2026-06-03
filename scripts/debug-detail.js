import axios from 'axios';
import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';

async function debugFull() {
  const homeUrl = 'http://nyjxxb.ijournals.cn/jcsam/home';
  try {
    console.log("1. 获取首页文章链接...");
    const homeRes = await axios.get(homeUrl, { responseType: 'arraybuffer' });
    const homeHtml = iconv.decode(homeRes.data, 'gbk');
    const $home = cheerio.load(homeHtml);
    
    const firstLink = $home('a[href*="abstract"]').first().attr('href');
    if (!firstLink) {
      console.log("未发现摘要链接");
      return;
    }
    
    const detailUrl = firstLink.startsWith('http') ? firstLink : 'http://nyjxxb.ijournals.cn' + (firstLink.startsWith('/') ? '' : '/') + firstLink;
    console.log(`2. 访问详情页: ${detailUrl}`);
    
    const detailRes = await axios.get(detailUrl, { responseType: 'arraybuffer' });
    const detailHtml = iconv.decode(detailRes.data, 'gbk');
    const $detail = cheerio.load(detailHtml);
    
    console.log("--- 详情页 HTML 分析 ---");
    // Most abstract pages in this system have a div with class 'des' or specific IDs
    const abstract = $detail('.des').text().trim() || $detail('div:contains("摘要：")').text().trim();
    console.log("Abstract Found:", abstract.substring(0, 300));

  } catch (e) {
    console.error(e.message);
  }
}

debugFull();
