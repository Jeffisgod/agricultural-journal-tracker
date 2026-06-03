"""
农业期刊论文数据获取脚本
使用 OpenAlex API 获取英文期刊论文数据
支持中英文期刊（中文期刊待接入）
"""

import requests
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# OpenAlex API 基础URL
OPENALEX_BASE_URL = "https://api.openalex.org"

# 英文期刊配置
JOURNALS = {
    "Smart Agricultural Technology": {
        "search_name": "Smart Agricultural Technology",
        "alternate_names": ["Smart Agricultural Technology"]
    },
    "Artificial Intelligence in Agriculture": {
        "search_name": "Artificial Intelligence in Agriculture",
        "alternate_names": ["Artificial Intelligence in Agriculture"]
    },
    "Computers and Electronics in Agriculture": {
        "search_name": "Computers and Electronics in Agriculture",
        "alternate_names": ["Computers and Electronics in Agriculture"]
    },
    "Biosystems Engineering": {
        "search_name": "Biosystems Engineering",
        "alternate_names": ["Biosystems Engineering"]
    }
}

# 中文期刊配置（待接入 - 知网RSS已停用）
CN_JOURNALS = {
    "农业工程学报": {
        "code": "NYGU",
        "source": "cnki",
        "status": "pending",
        "note": "知网RSS接口已停用，建议：1.使用知网研学导出 2.邮件订阅提醒 3.手动添加"
    },
    "农业机械学报": {
        "code": "NYJX",
        "source": "cnki",
        "status": "pending",
        "note": "待接入"
    },
    "排灌机械工程学报": {
        "code": "PGJX",
        "source": "cnki",
        "status": "pending",
        "note": "待接入"
    },
    "中国农业科学": {
        "code": "ZNYK",
        "source": "cnki",
        "status": "pending",
        "note": "待接入"
    }
}

class OpenAlexCrawler:
    def __init__(self, data_dir: str = "src"):
        self.data_dir = data_dir
        self.data_file = os.path.join(data_dir, "papers.json")
        self.state_file = os.path.join(data_dir, "crawler_state.json")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "mailto:your-email@example.com"
        })
        self.journal_ids = {}
        
    def load_existing_data(self) -> Dict:
        """加载已有数据"""
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"papers": [], "last_update": None, "journals": {}, "cn_journals": {}}
    
    def load_state(self) -> Dict:
        """加载爬虫状态"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"last_fetch": {}, "total_papers": 0, "journal_ids": {}}
    
    def save_state(self, state: Dict):
        """保存爬虫状态"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    
    def get_journal_id(self, journal_name: str, journal_config: Dict) -> Optional[str]:
        """通过期刊名称获取期刊 ID"""
        state = self.load_state()
        cached_id = state.get("journal_ids", {}).get(journal_name)
        if cached_id:
            return cached_id
        
        search_name = journal_config.get("search_name", journal_name)
        
        try:
            url = f"{OPENALEX_BASE_URL}/sources"
            params = {"search": search_name, "per_page": 5}
            
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            results = data.get("results", [])
            
            for source in results:
                display_name = source.get("display_name", "")
                if search_name.lower() in display_name.lower() or display_name.lower() in search_name.lower():
                    journal_id = source.get("id", "").replace("https://openalex.org/", "")
                    state["journal_ids"] = state.get("journal_ids", {})
                    state["journal_ids"][journal_name] = journal_id
                    self.save_state(state)
                    print(f"[OpenAlex] 找到期刊: {display_name} (ID: {journal_id})")
                    return journal_id
                    
            print(f"[Warning] 未找到期刊: {journal_name}")
            return None
            
        except Exception as e:
            print(f"[Error] 搜索期刊失败: {e}")
            return None
    
    def fetch_journal_papers(self, journal_name: str, journal_config: Dict, 
                              days_back: int = 30) -> List[Dict]:
        """从 OpenAlex 获取指定期刊的论文"""
        papers = []
        
        journal_id = self.get_journal_id(journal_name, journal_config)
        if not journal_id:
            print(f"[Warning] 无法获取 {journal_name} 的期刊ID，跳过")
            return papers
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_back)
        
        url = f"{OPENALEX_BASE_URL}/works"
        params = {
            "filter": f"primary_location.source.id:{journal_id},from_publication_date:{start_date.strftime('%Y-%m-%d')}",
            "sort": "publication_date:desc",
            "per_page": 25,
        }
        
        try:
            print(f"[OpenAlex] 正在获取: {journal_name}...")
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            results = data.get("results", [])
            
            print(f"[OpenAlex] {journal_name} 获取到 {len(results)} 篇论文")
            
            for work in results:
                paper = self.parse_work(work, journal_name)
                if paper:
                    papers.append(paper)
                    
        except requests.exceptions.RequestException as e:
            print(f"[Error] 获取 {journal_name} 失败: {e}")
            if hasattr(e.response, 'text'):
                print(f"[Error] 响应内容: {e.response.text[:200]}")
            
        return papers
    
    def parse_work(self, work: Dict, journal_name: str) -> Optional[Dict]:
        """解析 OpenAlex Work 对象为本地数据结构"""
        try:
            title = work.get("title", "")
            if not title:
                return None
            
            abstract = ""
            if work.get("abstract"):
                abstract = work["abstract"]
            elif work.get("inverted_index"):
                abstract = self.reconstruct_abstract(work["inverted_index"])
            
            authors = []
            authorships = work.get("authorships", [])
            for auth in authorships[:5]:
                author_name = auth.get("author", {}).get("display_name", "")
                if author_name:
                    authors.append(author_name)
            
            primary_location = work.get("primary_location", {})
            source = primary_location.get("source", {}) if primary_location else {}
            venue_name = source.get("display_name", journal_name) if source else journal_name
            
            pub_date = work.get("publication_date", "")
            if not pub_date:
                pub_date = datetime.now().strftime("%Y-%m-%d")
            
            keywords = []
            concepts = work.get("concepts", [])
            for concept in concepts[:5]:
                keyword = concept.get("display_name", "")
                if keyword:
                    keywords.append(keyword)
            
            open_access = work.get("open_access", {})
            is_oa = open_access.get("is_oa", False)
            oa_url = open_access.get("oa_url", "")
            
            paper = {
                "id": work.get("id", "").replace("https://openalex.org/", ""),
                "title": title,
                "abstract": abstract if abstract else "暂无摘要",
                "authors": authors if authors else ["Unknown"],
                "date": pub_date,
                "journal": venue_name,
                "journal_source": journal_name,
                "language": "en",
                "keywords": keywords,
                "doi": work.get("doi", ""),
                "open_access": is_oa,
                "pdf_url": oa_url,
                "url": work.get("id", "").replace("https://openalex.org/", "https://openalex.org/works/"),
                "cited_by_count": work.get("cited_by_count", 0),
                "type": work.get("type", "article"),
                "fetched_at": datetime.now().isoformat()
            }
            
            return paper
            
        except Exception as e:
            print(f"[Error] 解析论文失败: {e}")
            return None
    
    def reconstruct_abstract(self, inverted_index: Dict) -> str:
        """从 inverted_index 重建摘要文本"""
        if not inverted_index:
            return ""
        
        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        
        word_positions.sort(key=lambda x: x[0])
        words = [word for _, word in word_positions]
        return " ".join(words)
    
    def merge_papers(self, existing: List[Dict], new_papers: List[Dict]) -> List[Dict]:
        """合并新旧论文数据（增量更新）"""
        paper_dict = {p["id"]: p for p in existing}
        
        for paper in new_papers:
            paper_id = paper["id"]
            if paper_id in paper_dict:
                old_paper = paper_dict[paper_id]
                paper["is_read"] = old_paper.get("is_read", False)
                paper["is_favorite"] = old_paper.get("is_favorite", False)
                paper["notes"] = old_paper.get("notes", "")
                paper_dict[paper_id] = paper
            else:
                paper["is_read"] = False
                paper["is_favorite"] = False
                paper["notes"] = ""
                paper_dict[paper_id] = paper
        
        papers = list(paper_dict.values())
        papers.sort(key=lambda x: x.get("date", ""), reverse=True)
        
        return papers
    
    def run(self, days_back: int = 30):
        """运行数据获取任务"""
        print("=" * 60)
        print("农业期刊论文数据获取任务")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)
        
        data = self.load_existing_data()
        state = self.load_state()
        
        all_new_papers = []
        journal_stats = {}
        
        # 获取英文期刊论文
        print("\n[1/2] 获取英文期刊论文...")
        for journal_name, journal_config in JOURNALS.items():
            papers = self.fetch_journal_papers(journal_name, journal_config, days_back)
            all_new_papers.extend(papers)
            journal_stats[journal_name] = len(papers)
        
        # 中文期刊状态
        print("\n[2/2] 中文期刊状态...")
        for cn_name, cn_config in CN_JOURNALS.items():
            print(f"  {cn_name}: {cn_config['status']} - {cn_config['note']}")
        
        existing_papers = data.get("papers", [])
        merged_papers = self.merge_papers(existing_papers, all_new_papers)
        
        output_data = {
            "papers": merged_papers,
            "last_update": datetime.now().isoformat(),
            "journals": {
                name: {"count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                for name in JOURNALS.keys()
            },
            "cn_journals": CN_JOURNALS,
            "stats": {
                "total": len(merged_papers),
                "new_added": len(all_new_papers),
                "by_journal": journal_stats,
                "by_language": {
                    "en": sum(1 for p in merged_papers if p.get("language") == "en"),
                    "cn": sum(1 for p in merged_papers if p.get("language") == "cn")
                }
            }
        }
        
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        state["last_fetch"] = {name: datetime.now().isoformat() for name in JOURNALS.keys()}
        state["total_papers"] = len(merged_papers)
        self.save_state(state)
        
        print("\n" + "=" * 60)
        print(f"任务完成！")
        print(f"新增论文: {len(all_new_papers)} 篇")
        print(f"总论文数: {len(merged_papers)} 篇")
        print("各期刊统计:")
        for name, count in journal_stats.items():
            print(f"  - {name}: {count} 篇")
        print("=" * 60)
        
        return output_data


def main():
    crawler = OpenAlexCrawler()
    data = crawler.run(days_back=30)
    return data


if __name__ == "__main__":
    main()
