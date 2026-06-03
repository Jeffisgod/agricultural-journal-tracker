
import axios from 'axios';
import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';

async function debugDetail() {
    const url = 'http://nyjxxb.ijournals.cn/jcsam/article/abstract/20260701'; // Real link from debug-links
    console.log(`Fetching ${url}...`);
    try {
        const res = await axios.get(url, { responseType: 'arraybuffer' });
        const html = iconv.decode(res.data, 'gbk');
        const $ = cheerio.load(html);
        
        console.log('--- Title ---');
        console.log($('.article-title').text().trim() || $('h1').first().text().trim());
        
        console.log('--- Abstract Selectors ---');
        console.log('.abstract-content:', $('.abstract-content').text().trim());
        console.log('.des:', $('.des').text().trim());
        console.log('#abstract:', $('#abstract').text().trim());
        console.log('div with text 摘要：', $('div:contains("摘要：")').last().text().trim());
        
        // Let's find where the abstract actually is
        $('div, p, span').each((i, el) => {
            const text = $(el).text().trim();
            if (text.includes('摘要') || text.includes('鎽樿')) {
                console.log('Found block with 摘要:', text.substring(0, 500));
            }
        });
    } catch (e) {
        console.error('Error:', e.message);
    }
}

debugDetail();
