import axios from 'axios';
import * as cheerio from 'cheerio';

async function testCn() {
  try {
    const res1 = await axios.get('http://www.tcsae.org/');
    console.log("tcsae size:", res1.data.length);
    const $1 = cheerio.load(res1.data);
    console.log("tcsae title:", $1('title').text());
  } catch(e) { console.log('tcsae err', e.message); }

  try {
    const res2 = await axios.get('http://www.j-csam.org/');
    console.log("j-csam size:", res2.data.length);
    const $2 = cheerio.load(res2.data);
    console.log("j-csam title:", $2('title').text());
  } catch(e) { console.log('j-csam err', e.message); }
}

testCn();