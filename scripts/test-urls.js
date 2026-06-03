import axios from 'axios';

async function testUrls() {
  const urls = [
    'http://nygcxb.ijournals.cn/nygcxb/home',
    'http://zgnykx.ijournals.cn/zgnykx/home'
  ];
  for (const url of urls) {
    try {
      const res = await axios.get(url, { timeout: 10000 });
      console.log(`[Success] ${url} status: ${res.status}`);
    } catch (e) {
      console.log(`[Fail] ${url} error: ${e.message}`);
    }
  }
}

testUrls();
