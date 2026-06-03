
import axios from 'axios';
import * as cheerio from 'cheerio';
import iconv from 'iconv-lite';

async function inspectHtml() {
    const url = 'http://nyjxxb.ijournals.cn/jcsam/article/abstract/20260701';
    try {
        const res = await axios.get(url, { responseType: 'arraybuffer' });
        const html = iconv.decode(res.data, 'gbk');
        console.log(html.substring(0, 5000));
    } catch (e) {
        console.error(e.message);
    }
}

inspectHtml();
