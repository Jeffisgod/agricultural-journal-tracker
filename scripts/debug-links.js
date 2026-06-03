import axios from 'axios';
import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';

async function findLinks() {
  const url = 'http://www.tcsae.org/CN/article/showTenRecentlyReleasedArticle.do';
  try {
    const res = await axios.get(url, { responseType: 'arraybuffer' });
    const html = iconv.decode(res.data, 'gbk');
    const $ = cheerio.load(html);
    
    console.log("--- Links found on ChinaAgriSci ---");
    $('a').each((i, el) => {
      const text = $(el).text().trim();
      const href = $(el).attr('href');
      console.log(`[${text}] -> ${href}`);
    });
  } catch (e) {
    console.error(e.message);
  }
}

findLinks();
