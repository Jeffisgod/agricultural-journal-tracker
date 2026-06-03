import Parser from 'rss-parser';

const parser = new Parser();

async function test() {
  const feedUrls = [
    'https://rss.sciencedirect.com/publication/science/27723755',
    'https://rss.sciencedirect.com/publication/science/25897217',
    'https://rss.sciencedirect.com/publication/science/01681699'
  ];

  for (let url of feedUrls) {
    try {
      console.log('Fetching', url);
      const feed = await parser.parseURL(url);
      console.log('Success:', feed.title, feed.items.length);
    } catch(e) {
      console.log("Error fetching", url, e.message);
    }
  }
}

test();