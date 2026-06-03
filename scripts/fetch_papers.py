"""
农业期刊论文数据获取脚本
使用 OpenAlex API 获取英文期刊论文数据
支持中英文期刊（中文期刊待接入）
"""

import argparse
import requests
import json
import os
import re
import sqlite3
from io import BytesIO
from html import unescape
from collections import Counter
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from urllib.parse import quote
import xml.etree.ElementTree as ET
try:
    from deep_translator import GoogleTranslator
except ImportError:
    GoogleTranslator = None
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# OpenAlex API 基础URL
OPENALEX_BASE_URL = "https://api.openalex.org"

# 英文期刊配置
JOURNALS = {
    "Information Processing in Agriculture": {
        "search_name": "Information Processing in Agriculture",
        "alternate_names": ["Information Processing in Agriculture"]
    },
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

# 中文期刊配置
CN_JOURNALS = {
    "农业工程学报": {
        "search_name": "Nongye gongcheng xuebao",
        "issn": "1002-6819"
    },
    "农业机械学报": {
        "search_name": "Transactions of the Chinese Society of Agricultural Machinery",
        "issn": "1000-1298"
    }
}

CV_JOURNALS = {
    "arXiv cs.CV Recent": {
        "list_url": "https://arxiv.org/list/cs.CV/recent",
        "category": "cs.CV",
        "max_results": 50
    }
}

class OpenAlexCrawler:
    def __init__(self, data_dir: str = "public"):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.data_dir = data_dir
        self.data_file = os.path.join(data_dir, "papers.json")
        self.state_file = os.path.join(data_dir, "crawler_state.json")
        self.storage_dir = os.path.join(self.project_root, "storage")
        self.db_file = os.path.join(self.storage_dir, "papers.db")
        self.kb_file = os.path.join(self.storage_dir, "knowledge_base.json")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        })
        self.journal_ids = {}
        self.translator = GoogleTranslator(source='auto', target='zh-CN') if GoogleTranslator else None
        
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
        return {
            "last_fetch": {},
            "total_papers": 0,
            "journal_ids": {},
            "abstract_cache": {},
            "storage": {},
            "last_run_stats": {},
            "failed_abstract_papers": {}  # {paper_id: {"last_tried": "...", "retry_count": 0}}
        }
    
    def save_state(self, state: Dict):
        """保存爬虫状态"""
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def parse_iso_datetime(self, value: str) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def get_paper_id(self, work: Dict) -> str:
        return work.get("id", "").replace("https://openalex.org/", "")

    def get_existing_paper_ids(self, papers: List[Dict]) -> set:
        return {paper.get("id") for paper in papers if paper.get("id")}

    def get_incremental_start_date(self, journal_name: str, days_back: int) -> datetime:
        state = self.load_state()
        base_start = datetime.now() - timedelta(days=days_back)
        last_fetch = self.parse_iso_datetime(state.get("last_fetch", {}).get(journal_name, ""))
        if not last_fetch:
            return base_start
        incremental_start = last_fetch - timedelta(days=3)
        return max(base_start, incremental_start)

    def normalize_doi(self, doi: str) -> str:
        value = (doi or "").strip()
        value = re.sub(r"^https?://(dx\.)?doi\.org/", "", value, flags=re.IGNORECASE)
        value = re.sub(r"^doi:\s*", "", value, flags=re.IGNORECASE)
        return value.strip().strip("<>")

    def clean_abstract_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = unescape(text)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        cleaned = re.sub(r"^(abstract|summary)\s*[:：-]?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(摘要)\s*[:：-]?\s*", "", cleaned)
        return cleaned.strip()

    def is_valid_abstract(self, text: str) -> bool:
        if not text:
            return False
        lowered = text.lower()
        invalid_markers = [
            "skip to main content",
            "download pdf",
            "copyright",
            "all rights reserved",
            "sign in",
            "log in",
            "view full text"
        ]
        return len(text) >= 60 and not any(marker in lowered for marker in invalid_markers)

    def get_cached_abstract(self, cache_key: str) -> str:
        if not cache_key:
            return ""
        state = self.load_state()
        return state.get("abstract_cache", {}).get(cache_key, "")

    def save_cached_abstract(self, cache_key: str, abstract: str):
        if not cache_key or not abstract:
            return
        state = self.load_state()
        state.setdefault("abstract_cache", {})[cache_key] = abstract
        self.save_state(state)

    def extract_meta_content(self, html: str, meta_names: List[str]) -> str:
        if not html:
            return ""
        name_lookup = {name.lower() for name in meta_names}
        meta_tags = re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE)
        for meta_tag in meta_tags:
            name_match = re.search(r'(?:name|property)=["\']([^"\']+)["\']', meta_tag, flags=re.IGNORECASE)
            content_match = re.search(r'content=["\'](.*?)["\']', meta_tag, flags=re.IGNORECASE | re.DOTALL)
            if not name_match or not content_match:
                continue
            if name_match.group(1).strip().lower() in name_lookup:
                cleaned = self.clean_abstract_text(content_match.group(1))
                if self.is_valid_abstract(cleaned):
                    return cleaned
        return ""

    def extract_meta_values(self, html: str, meta_name: str) -> List[str]:
        values = []
        if not html:
            return values
        meta_tags = re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE)
        for meta_tag in meta_tags:
            name_match = re.search(r'(?:name|property)=["\']([^"\']+)["\']', meta_tag, flags=re.IGNORECASE)
            content_match = re.search(r'content=["\'](.*?)["\']', meta_tag, flags=re.IGNORECASE | re.DOTALL)
            if not name_match or not content_match:
                continue
            if name_match.group(1).strip().lower() == meta_name.lower():
                content = self.clean_abstract_text(content_match.group(1))
                if content:
                    values.append(content)
        return values

    def extract_structured_abstract(self, html: str) -> str:
        if not html:
            return ""
        block_patterns = [
            r'<section[^>]+(?:id|class)=["\'][^"\']*(?:abstract|summary)[^"\']*["\'][^>]*>(.*?)</section>',
            r'<div[^>]+(?:id|class)=["\'][^"\']*(?:abstract|summary)[^"\']*["\'][^>]*>(.*?)</div>',
            r'<p[^>]+(?:id|class)=["\'][^"\']*(?:abstract|summary)[^"\']*["\'][^>]*>(.*?)</p>'
        ]
        for pattern in block_patterns:
            matches = re.findall(pattern, html, flags=re.IGNORECASE | re.DOTALL)
            for match in matches:
                cleaned = self.clean_abstract_text(match)
                if self.is_valid_abstract(cleaned):
                    return cleaned
        jsonld_descriptions = re.findall(r'"description"\s*:\s*"((?:\\.|[^"])*)"', html, flags=re.IGNORECASE)
        for description in jsonld_descriptions:
            cleaned = self.clean_abstract_text(description.replace('\\"', '"'))
            if self.is_valid_abstract(cleaned):
                return cleaned
        return ""

    def get_page_abstract(self, page_url: str) -> str:
        if not page_url:
            return ""
        cache_key = f"url:{page_url}"
        cached = self.get_cached_abstract(cache_key)
        if cached:
            return cached
        try:
            resp = self.session.get(
                page_url,
                timeout=10,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"
                }
            )
            if resp.status_code != 200:
                return ""
            html = resp.text
            meta_abstract = self.extract_meta_content(
                html,
                ["citation_abstract", "dc.description", "description", "og:description", "twitter:description"]
            )
            if meta_abstract:
                self.save_cached_abstract(cache_key, meta_abstract)
                return meta_abstract
            structured_abstract = self.extract_structured_abstract(html)
            if structured_abstract:
                self.save_cached_abstract(cache_key, structured_abstract)
                return structured_abstract
        except Exception:
            pass
        return ""
    
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
    
    def fetch_journal_papers(self, journal_name: str, journal_config: Dict, days_back: int = 30,
                              existing_paper_ids: Optional[set] = None) -> List[Dict]:
        """从 OpenAlex 获取指定期刊的论文"""
        papers = []
        existing_paper_ids = existing_paper_ids or set()
        
        # 优先使用预配置的 issn 或 id
        if "issn" in journal_config:
            filter_query = f"primary_location.source.issn:{journal_config['issn']}"
        elif "id" in journal_config:
            filter_query = f"primary_location.source.id:{journal_config['id']}"
        else:
            journal_id = self.get_journal_id(journal_name, journal_config)
            if not journal_id:
                print(f"[Warning] 无法获取 {journal_name} 的期刊ID，跳过")
                return papers
            filter_query = f"primary_location.source.id:{journal_id}"
        
        start_date = self.get_incremental_start_date(journal_name, days_back)
        
        url = f"{OPENALEX_BASE_URL}/works"
        
        page = 1
        max_pages = 5 if journal_name not in CN_JOURNALS else 5  # 英文最多5页(500篇)，中文最多5页(500篇)以防跑太久
        print(f"[OpenAlex] 正在获取: {journal_name} ({start_date.strftime('%Y-%m-%d')} 起)...")
        
        while page <= max_pages:
            params = {
                "filter": f"{filter_query},from_publication_date:{start_date.strftime('%Y-%m-%d')}",
                "sort": "publication_date:desc",
                "per_page": 100,
                "page": page
            }
            
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                
                data = response.json()
                results = data.get("results", [])
                
                if not results:
                    break

                all_known_in_page = True
                    
                for work in results:
                    paper_id = self.get_paper_id(work)
                    if paper_id and paper_id in existing_paper_ids:
                        continue
                    all_known_in_page = False
                    paper = self.parse_work(work, journal_name)
                    if paper:
                        papers.append(paper)
                        
                if len(results) < 100:
                    break
                if all_known_in_page:
                    break
                    
                page += 1
                
            except requests.exceptions.RequestException as e:
                print(f"[Error] 获取 {journal_name} 失败: {e}")
                if hasattr(e.response, 'text') and e.response:
                    print(f"[Error] 响应内容: {e.response.text[:200]}")
                break
                
        print(f"[OpenAlex] {journal_name} 共获取到 {len(papers)} 篇论文")
            
        return papers
    
    def get_crossref_abstract(self, doi: str) -> str:
        """如果 OpenAlex 缺失摘要，尝试从 Crossref 补充获取"""
        doi_id = self.normalize_doi(doi)
        if not doi_id:
            return ""
        cache_key = f"doi:{doi_id}"
        cached = self.get_cached_abstract(cache_key)
        if cached:
            return cached
        try:
            print(f"    [Crossref] 尝试补充摘要: {doi_id}")
            url = f"https://api.crossref.org/works/{doi_id}"
            resp = self.session.get(url, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                abstract = self.clean_abstract_text(data.get("message", {}).get("abstract", ""))
                if self.is_valid_abstract(abstract):
                    self.save_cached_abstract(cache_key, abstract)
                    print(f"    [Crossref] 成功获取补充摘要")
                    return abstract.strip()
        except Exception:
            print(f"    [Crossref] 补充失败或超时")
        return ""

    def get_best_effort_abstract(self, doi: str = "", page_url: str = "") -> str:
        abstract = ""
        if doi:
            # 1. 先尝试 Semantic Scholar（支持很多出版商的摘要）
            abstract = self.get_semantic_scholar_abstract(doi)
            if abstract:
                return abstract

            # 2. 再尝试 Crossref
            abstract = self.get_crossref_abstract(doi)
            if abstract:
                return abstract

            # 3. 最后尝试 Unpaywall + Semantic Scholar 联动
            abstract = self.get_unpaywall_abstract(doi)
            if abstract:
                return abstract

            # 4. 尝试 DOI 落地页
            doi_landing_url = f"https://doi.org/{quote(self.normalize_doi(doi), safe='/():')}"
            abstract = self.get_page_abstract(doi_landing_url)
            if abstract:
                print("    [Fallback] 通过 DOI 落地页补充摘要")
                return abstract

        if page_url:
            abstract = self.get_page_abstract(page_url)
            if abstract:
                print("    [Fallback] 通过论文页面补充摘要")
                return abstract
        return ""

    def get_semantic_scholar_abstract(self, doi: str) -> str:
        """通过 Semantic Scholar API 获取摘要"""
        doi_id = self.normalize_doi(doi)
        if not doi_id:
            return ""
        cache_key = f"ss:{doi_id}"
        cached = self.get_cached_abstract(cache_key)
        if cached:
            return cached
        try:
            url = f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi_id}?fields=title,abstract"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                abstract = data.get("abstract", "")
                if self.is_valid_abstract(abstract):
                    self.save_cached_abstract(cache_key, abstract)
                    print("    [SemanticScholar] 成功获取补充摘要")
                    return abstract.strip()
        except Exception:
            pass
        return ""

    def get_unpaywall_abstract(self, doi: str) -> str:
        """通过 Unpaywall API 获取 Semantic Scholar ID，再获取摘要"""
        doi_id = self.normalize_doi(doi)
        if not doi_id:
            return ""
        cache_key = f"up:{doi_id}"
        cached = self.get_cached_abstract(cache_key)
        if cached:
            return cached
        try:
            # Unpaywall 需要真实邮箱，随便填一个
            url = f"https://api.unpaywall.org/v2/{doi_id}?email=research@example.com"
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # Unpaywall 返回 Semantic Scholar 的 paper ID
                ss_id = data.get("semantic_scholar_id") or data.get("ss_paper_id")
                if ss_id:
                    ss_url = f"https://api.semanticscholar.org/graph/v1/paper/{ss_id}?fields=title,abstract"
                    resp2 = self.session.get(ss_url, timeout=10)
                    if resp2.status_code == 200:
                        ss_data = resp2.json()
                        abstract = ss_data.get("abstract", "")
                        if self.is_valid_abstract(abstract):
                            self.save_cached_abstract(cache_key, abstract)
                            print("    [Unpaywall+SS] 成功获取补充摘要")
                            return abstract.strip()
        except Exception:
            pass
        return ""

    def translate_text(self, text: str) -> str:
        if not text or not self.translator:
            return text
        try:
            if len(text) > 4000:
                translated = self.translator.translate(text[:4000])
                return f"{translated}..." if translated else text
            translated = self.translator.translate(text)
            return translated or text
        except Exception as e:
            print(f"  [Warning] 翻译失败: {e}")
            return text

    def init_database(self):
        os.makedirs(self.storage_dir, exist_ok=True)
        with sqlite3.connect(self.db_file) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    abstract TEXT,
                    journal TEXT,
                    journal_source TEXT,
                    language TEXT,
                    date TEXT,
                    doi TEXT,
                    url TEXT,
                    pdf_url TEXT,
                    open_access INTEGER,
                    cited_by_count INTEGER,
                    type TEXT,
                    authors_json TEXT,
                    keywords_json TEXT,
                    original_title TEXT,
                    original_abstract TEXT,
                    translated_title TEXT,
                    translated_abstract TEXT,
                    full_text TEXT,
                    fetched_at TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_chunks (
                    paper_id TEXT PRIMARY KEY,
                    journal_source TEXT,
                    language TEXT,
                    published_at TEXT,
                    keywords TEXT,
                    content TEXT,
                    updated_at TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_journal_source ON papers(journal_source)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_date ON papers(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_journal_source ON knowledge_chunks(journal_source)")
            columns = {row[1] for row in conn.execute("PRAGMA table_info(papers)").fetchall()}
            if "full_text" not in columns:
                conn.execute("ALTER TABLE papers ADD COLUMN full_text TEXT")
            conn.commit()

    def build_knowledge_content(self, paper: Dict) -> str:
        authors = ", ".join(paper.get("authors", []))
        keywords = ", ".join(paper.get("keywords", []))
        fields = [
            f"标题: {paper.get('title', '')}",
            f"原始标题: {paper.get('original_title', '')}",
            f"翻译标题: {paper.get('translated_title', '')}",
            f"摘要: {paper.get('abstract', '')}",
            f"原始摘要: {paper.get('original_abstract', '')}",
            f"翻译摘要: {paper.get('translated_abstract', '')}",
            f"全文: {paper.get('full_text', '')}",
            f"作者: {authors}",
            f"期刊: {paper.get('journal_source', '')}",
            f"日期: {paper.get('date', '')}",
            f"关键词: {keywords}",
            f"DOI: {paper.get('doi', '')}"
        ]
        return "\n".join([field for field in fields if field.split(": ", 1)[-1]])

    def sync_database(self, papers: List[Dict]):
        self.init_database()
        now = datetime.now().isoformat()
        with sqlite3.connect(self.db_file) as conn:
            conn.executemany("""
                INSERT INTO papers (
                    id, title, abstract, journal, journal_source, language, date, doi, url, pdf_url,
                    open_access, cited_by_count, type, authors_json, keywords_json,
                    original_title, original_abstract, translated_title, translated_abstract,
                    full_text, fetched_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    abstract=excluded.abstract,
                    journal=excluded.journal,
                    journal_source=excluded.journal_source,
                    language=excluded.language,
                    date=excluded.date,
                    doi=excluded.doi,
                    url=excluded.url,
                    pdf_url=excluded.pdf_url,
                    open_access=excluded.open_access,
                    cited_by_count=excluded.cited_by_count,
                    type=excluded.type,
                    authors_json=excluded.authors_json,
                    keywords_json=excluded.keywords_json,
                    original_title=excluded.original_title,
                    original_abstract=excluded.original_abstract,
                    translated_title=excluded.translated_title,
                    translated_abstract=excluded.translated_abstract,
                    full_text=excluded.full_text,
                    fetched_at=excluded.fetched_at,
                    updated_at=excluded.updated_at
            """, [
                (
                    paper.get("id", ""),
                    paper.get("title", ""),
                    paper.get("abstract", ""),
                    paper.get("journal", ""),
                    paper.get("journal_source", ""),
                    paper.get("language", ""),
                    paper.get("date", ""),
                    paper.get("doi", ""),
                    paper.get("url", ""),
                    paper.get("pdf_url", ""),
                    1 if paper.get("open_access") else 0,
                    paper.get("cited_by_count", 0),
                    paper.get("type", ""),
                    json.dumps(paper.get("authors", []), ensure_ascii=False),
                    json.dumps(paper.get("keywords", []), ensure_ascii=False),
                    paper.get("original_title", ""),
                    paper.get("original_abstract", ""),
                    paper.get("translated_title", ""),
                    paper.get("translated_abstract", ""),
                    paper.get("full_text", ""),
                    paper.get("fetched_at", ""),
                    now
                )
                for paper in papers
            ])
            conn.executemany("""
                INSERT INTO knowledge_chunks (
                    paper_id, journal_source, language, published_at, keywords, content, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(paper_id) DO UPDATE SET
                    journal_source=excluded.journal_source,
                    language=excluded.language,
                    published_at=excluded.published_at,
                    keywords=excluded.keywords,
                    content=excluded.content,
                    updated_at=excluded.updated_at
            """, [
                (
                    paper.get("id", ""),
                    paper.get("journal_source", ""),
                    paper.get("language", ""),
                    paper.get("date", ""),
                    ", ".join(paper.get("keywords", [])),
                    self.build_knowledge_content(paper),
                    now
                )
                for paper in papers
            ])
            conn.commit()

    def backfill_abstracts(self, existing_papers: List[Dict]) -> List[Dict]:
        """对已有数据中缺失摘要的论文进行二次补充（带渐进重试）"""
        state = self.load_state()
        failed_papers = state.get("failed_abstract_papers", {})
        now = datetime.now()

        # 需要尝试补充的论文：无摘要 AND (从未尝试过 OR 距上次失败超过7天)
        papers_need_abstract = []
        for paper in existing_papers:
            if (not paper.get("abstract") or paper.get("abstract") == "暂无摘要") and paper.get("doi"):
                pid = paper.get("id", "")
                failed_info = failed_papers.get(pid, {})
                last_tried = failed_info.get("last_tried", "")
                retry_count = failed_info.get("retry_count", 0)

                if not last_tried:
                    # 从未尝试过
                    papers_need_abstract.append(paper)
                else:
                    # 距上次失败超过7天则重试
                    try:
                        last_dt = datetime.fromisoformat(last_tried)
                        if (now - last_dt).days >= 7:
                            papers_need_abstract.append(paper)
                    except ValueError:
                        papers_need_abstract.append(paper)

        if not papers_need_abstract:
            print("[回填] 所有已有论文摘要已尝试或距上次重试不足7天，跳过")
            return existing_papers

        print(f"[回填] 发现 {len(papers_need_abstract)} 篇论文缺少摘要，开始补充（带7天重试间隔）...")
        updated_count = 0
        failed_count = 0
        for i, paper in enumerate(papers_need_abstract):
            doi = paper.get("doi", "")
            page_url = paper.get("url", "")
            pid = paper.get("id", "")

            # 跳过已知无摘要的来源
            if any(domain in page_url for domain in ["linkinghub.elsevier.com"]):
                failed_papers[pid] = {"last_tried": now.isoformat(), "retry_count": failed_papers.get(pid, {}).get("retry_count", 0) + 1}
                continue

            abstract = self.get_best_effort_abstract(doi=doi, page_url=page_url)
            if abstract and abstract != "暂无摘要":
                paper["abstract"] = abstract
                updated_count += 1
                # 成功后从失败列表移除
                if pid in failed_papers:
                    del failed_papers[pid]
                print(f"    [{i+1}/{len(papers_need_abstract)}] ✅ 补充成功: {paper.get('title', '')[:50]}")
            else:
                failed_count += 1
                failed_papers[pid] = {"last_tried": now.isoformat(), "retry_count": failed_papers.get(pid, {}).get("retry_count", 0) + 1}

            # 每批 5 篇后短暂休息，避免频率限制
            if (i + 1) % 5 == 0:
                import time
                time.sleep(2)

        state["failed_abstract_papers"] = failed_papers
        self.save_state(state)

        print(f"[回填] 完成，成功补充 {updated_count} 篇，失败 {failed_count} 篇（将在7天后重试）")
        return existing_papers

    def export_knowledge_base(self, papers: List[Dict]):
        os.makedirs(self.storage_dir, exist_ok=True)
        journal_counter = Counter(paper.get("journal_source", "") for paper in papers if paper.get("journal_source"))
        keyword_counter = Counter()
        for paper in papers:
            keyword_counter.update(paper.get("keywords", []))
        knowledge_entries = [
            {
                "paper_id": paper.get("id", ""),
                "title": paper.get("title", ""),
                "journal_source": paper.get("journal_source", ""),
                "date": paper.get("date", ""),
                "language": paper.get("language", ""),
                "keywords": paper.get("keywords", []),
                "content": self.build_knowledge_content(paper)
            }
            for paper in papers
        ]
        knowledge_base = {
            "generated_at": datetime.now().isoformat(),
            "total_papers": len(papers),
            "journals": [{"name": name, "count": count} for name, count in journal_counter.most_common()],
            "top_keywords": [{"keyword": keyword, "count": count} for keyword, count in keyword_counter.most_common(50)],
            "entries": knowledge_entries
        }
        with open(self.kb_file, 'w', encoding='utf-8') as f:
            json.dump(knowledge_base, f, ensure_ascii=False, indent=2)

    def search_knowledge_base(self, query: str, limit: int = 10) -> List[Dict]:
        if not os.path.exists(self.db_file):
            return []
        pattern = f"%{query.strip()}%"
        with sqlite3.connect(self.db_file) as conn:
            rows = conn.execute("""
                SELECT p.id, p.title, p.journal_source, p.date, p.language, k.content
                FROM papers p
                JOIN knowledge_chunks k ON k.paper_id = p.id
                WHERE p.title LIKE ?
                   OR p.abstract LIKE ?
                   OR p.full_text LIKE ?
                   OR p.journal_source LIKE ?
                   OR k.content LIKE ?
                ORDER BY p.date DESC
                LIMIT ?
            """, (pattern, pattern, pattern, pattern, pattern, limit)).fetchall()
        return [
            {
                "paper_id": row[0],
                "title": row[1],
                "journal_source": row[2],
                "date": row[3],
                "language": row[4],
                "content": row[5]
            }
            for row in rows
        ]

    def should_enrich_abstract(self, publication_date: str, journal_name: str) -> bool:
        if not publication_date:
            return False
        try:
            published_at = datetime.strptime(publication_date[:10], "%Y-%m-%d")
        except ValueError:
            return False
        if journal_name in CN_JOURNALS:
            return (datetime.now() - published_at).days <= 365
        # 英文期刊放宽到 180 天，覆盖更多新发表论文
        return (datetime.now() - published_at).days <= 180

    def parse_work(self, work: Dict, journal_name: str) -> Optional[Dict]:
        """解析 OpenAlex Work 对象为本地数据结构"""
        try:
            title = work.get("title", "")
            if not title:
                return None
            primary_location = work.get("primary_location", {}) or {}
            source = primary_location.get("source", {}) if primary_location else {}
            landing_page_url = primary_location.get("landing_page_url", "")
            pub_date = work.get("publication_date", "")
            if not pub_date:
                pub_date = datetime.now().strftime("%Y-%m-%d")
            
            abstract = ""
            if work.get("abstract"):
                abstract = work["abstract"]
            elif work.get("abstract_inverted_index"):
                abstract = self.reconstruct_abstract(work["abstract_inverted_index"])
            
            doi_url = work.get("doi", "")
            if not abstract and self.should_enrich_abstract(pub_date, journal_name):
                abstract = self.get_best_effort_abstract(doi=doi_url, page_url=landing_page_url)

            is_cn_journal = journal_name in CN_JOURNALS
            original_title = title
            original_abstract = abstract
            translated_title = ""
            translated_abstract = ""
            if is_cn_journal:
                if title and not re.search(r'[\u4e00-\u9fa5]', title):
                    translated_title = self.translate_text(title)
                    title = translated_title or title
                if abstract and not re.search(r'[\u4e00-\u9fa5]', abstract):
                    translated_abstract = self.translate_text(abstract)
                    abstract = translated_abstract or abstract

            authors = []
            authorships = work.get("authorships", [])
            for auth in authorships[:5]:
                author_name = auth.get("author", {}).get("display_name", "")
                if author_name:
                    authors.append(author_name)
            
            venue_name = source.get("display_name", journal_name) if source else journal_name
            
            keywords = []
            concepts = work.get("concepts", [])
            for concept in concepts[:5]:
                keyword = concept.get("display_name", "")
                if keyword:
                    keywords.append(keyword)
            
            open_access = work.get("open_access", {})
            is_oa = open_access.get("is_oa", False)
            oa_url = open_access.get("oa_url", "") or primary_location.get("pdf_url", "")
            openalex_url = work.get("id", "").replace("https://openalex.org/", "https://openalex.org/works/")
            paper_url = landing_page_url or openalex_url
            
            paper = {
                "id": work.get("id", "").replace("https://openalex.org/", ""),
                "title": title,
                "abstract": abstract if abstract else "暂无摘要",
                "authors": authors if authors else ["Unknown"],
                "date": pub_date,
                "journal": venue_name,
                "journal_source": journal_name,
                "language": "en",
                "original_title": original_title if original_title != title else "",
                "original_abstract": original_abstract if original_abstract and original_abstract != abstract else "",
                "translated_title": translated_title if translated_title and translated_title != original_title else "",
                "translated_abstract": translated_abstract if translated_abstract and translated_abstract != original_abstract else "",
                "keywords": keywords,
                "doi": work.get("doi", ""),
                "open_access": is_oa,
                "pdf_url": oa_url,
                "url": paper_url,
                "openalex_url": openalex_url,
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

    def extract_arxiv_full_text(self, pdf_url: str) -> str:
        if not pdf_url or not PdfReader:
            return ""
        cache_key = f"fulltext:{pdf_url}"
        cached = self.get_cached_abstract(cache_key)
        if cached:
            return cached
        try:
            response = self.session.get(pdf_url, timeout=60)
            response.raise_for_status()
            reader = PdfReader(BytesIO(response.content))
            parts = []
            for page in reader.pages[:20]:
                page_text = " ".join((page.extract_text() or "").split())
                if page_text:
                    parts.append(page_text)
                if sum(len(part) for part in parts) >= 60000:
                    break
            full_text = "\n".join(parts).strip()
            if full_text:
                self.save_cached_abstract(cache_key, full_text)
            return full_text
        except Exception:
            return ""

    def fetch_arxiv_recent_ids(self, source_config: Dict) -> List[str]:
        try:
            response = self.session.get(source_config["list_url"], timeout=30)
            response.raise_for_status()
            ids = re.findall(r'arXiv:([a-z\-]+\/\d{7}|\d{4}\.\d{4,5}(?:v\d+)?)', response.text, flags=re.IGNORECASE)
            unique_ids = []
            seen = set()
            for paper_id in ids:
                normalized_id = paper_id.strip()
                if normalized_id not in seen:
                    seen.add(normalized_id)
                    unique_ids.append(normalized_id)
                if len(unique_ids) >= source_config.get("max_results", 50):
                    break
            return unique_ids
        except Exception as e:
            print(f"[Error] 获取 arXiv recent 列表失败: {e}")
            return []

    def parse_arxiv_abs_page(self, html: str, paper_id: str, source_name: str) -> Optional[Dict]:
        title = ""
        title_candidates = self.extract_meta_values(html, "citation_title") + self.extract_meta_values(html, "og:title")
        if title_candidates:
            title = title_candidates[0]
        if not title:
            title_match = re.search(r"<title>\s*(.*?)\s*</title>", html, flags=re.IGNORECASE | re.DOTALL)
            if title_match:
                title = self.clean_abstract_text(title_match.group(1).replace("arXiv:", ""))
        if not title:
            return None

        abstract = ""
        abstract_match = re.search(
            r'<blockquote[^>]*class=["\'][^"\']*abstract[^"\']*["\'][^>]*>(.*?)</blockquote>',
            html,
            flags=re.IGNORECASE | re.DOTALL
        )
        if abstract_match:
            abstract = self.clean_abstract_text(abstract_match.group(1))
        if not abstract:
            abstract = self.extract_meta_content(html, ["description", "og:description", "twitter:description"])
        if abstract.lower().startswith("abstract:"):
            abstract = abstract.split(":", 1)[1].strip()

        authors = self.extract_meta_values(html, "citation_author")[:5]
        if not authors:
            author_blocks = re.findall(r'<a[^>]+href=["\']/search/\?searchtype=author[^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL)
            authors = [self.clean_abstract_text(author) for author in author_blocks[:5] if self.clean_abstract_text(author)]

        date = ""
        date_candidates = self.extract_meta_values(html, "citation_date")
        if date_candidates:
            date = date_candidates[0]
        if not date:
            date_match = re.search(r'\[v1\]\s*[A-Za-z]{3},\s*(\d{1,2}\s+\w+\s+\d{4})', html, flags=re.IGNORECASE)
            if date_match:
                try:
                    date = datetime.strptime(date_match.group(1), "%d %b %Y").strftime("%Y-%m-%d")
                except ValueError:
                    date = ""

        normalized_entry_id = re.sub(r"v\d+$", "", paper_id)
        pdf_url = f"https://arxiv.org/pdf/{normalized_entry_id}.pdf"
        full_text = self.extract_arxiv_full_text(pdf_url)
        return {
            "id": f"arxiv-{normalized_entry_id}",
            "title": title,
            "abstract": abstract if abstract else "暂无摘要",
            "authors": authors if authors else ["Unknown"],
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "journal": "arXiv",
            "journal_source": source_name,
            "language": "en",
            "keywords": ["cs.CV", "Computer Vision and Pattern Recognition"],
            "doi": f"https://doi.org/10.48550/arXiv.{normalized_entry_id}",
            "open_access": True,
            "pdf_url": pdf_url,
            "url": f"https://arxiv.org/abs/{normalized_entry_id}",
            "cited_by_count": 0,
            "type": "preprint",
            "full_text": full_text,
            "fetched_at": datetime.now().isoformat()
        }

    def parse_arxiv_feed(self, feed_xml: str, source_name: str) -> List[Dict]:
        papers = []
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom"
        }
        try:
            root = ET.fromstring(feed_xml)
        except ET.ParseError:
            return papers

        for entry in root.findall("atom:entry", ns):
            abs_url = entry.findtext("atom:id", default="", namespaces=ns)
            entry_id = abs_url.rstrip("/").split("/")[-1]
            normalized_entry_id = re.sub(r"v\d+$", "", entry_id)
            title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
            if not title:
                continue
            abstract = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
            authors = []
            for author in entry.findall("atom:author", ns)[:5]:
                author_name = author.findtext("atom:name", default="", namespaces=ns)
                if author_name:
                    authors.append(author_name)
            categories = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", ns) if cat.attrib.get("term")]
            pdf_url = ""
            for link in entry.findall("atom:link", ns):
                href = link.attrib.get("href", "")
                if link.attrib.get("title") == "pdf" or "/pdf/" in href:
                    pdf_url = href
                    break
            doi_value = entry.findtext("arxiv:doi", default="", namespaces=ns)
            if doi_value:
                doi_url = f"https://doi.org/{doi_value}"
            else:
                doi_url = f"https://doi.org/10.48550/arXiv.{normalized_entry_id}"
            published = entry.findtext("atom:published", default="", namespaces=ns)
            paper = {
                "id": f"arxiv-{normalized_entry_id}",
                "title": title,
                "abstract": abstract if abstract else "暂无摘要",
                "authors": authors if authors else ["Unknown"],
                "date": published[:10] if published else datetime.now().strftime("%Y-%m-%d"),
                "journal": "arXiv",
                "journal_source": source_name,
                "language": "en",
                "keywords": categories[:5],
                "doi": doi_url,
                "open_access": True,
                "pdf_url": pdf_url or f"https://arxiv.org/pdf/{normalized_entry_id}.pdf",
                "url": abs_url or f"https://arxiv.org/abs/{normalized_entry_id}",
                "cited_by_count": 0,
                "type": "preprint",
                "fetched_at": datetime.now().isoformat()
            }
            papers.append(paper)
        return papers

    def fetch_arxiv_recent_papers(self, source_name: str, source_config: Dict,
                                  existing_paper_ids: Optional[set] = None) -> List[Dict]:
        print(f"[arXiv] 正在获取: {source_name}...")
        existing_paper_ids = existing_paper_ids or set()
        recent_ids = self.fetch_arxiv_recent_ids(source_config)
        if not recent_ids:
            return []
        papers = []
        for paper_id in recent_ids:
            normalized_entry_id = re.sub(r"v\d+$", "", paper_id)
            if f"arxiv-{normalized_entry_id}" in existing_paper_ids:
                continue
            try:
                response = self.session.get(f"https://arxiv.org/abs/{paper_id}", timeout=30)
                response.raise_for_status()
                paper = self.parse_arxiv_abs_page(response.text, paper_id, source_name)
                if paper:
                    papers.append(paper)
            except Exception as e:
                print(f"[Error] 获取 arXiv 论文失败: {paper_id} {e}")
        papers.sort(key=lambda x: x.get("date", ""), reverse=True)
        print(f"[arXiv] {source_name} 共获取到 {len(papers)} 篇论文")
        return papers
    
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
    
    def run(self, days_back: int = 365, backfill: bool = False):
        """运行数据获取任务"""
        print("=" * 60)
        print("农业期刊论文数据获取任务 (近一年快速抓取)")
        print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 60)

        data = self.load_existing_data()
        state = self.load_state()
        existing_papers = data.get("papers", [])
        existing_paper_ids = self.get_existing_paper_ids(existing_papers)
        
        all_new_papers = []
        journal_stats = {}
        
        # 获取英文期刊论文
        print("\n[1/2] 获取英文期刊论文...")
        for journal_name, journal_config in JOURNALS.items():
            papers = self.fetch_journal_papers(journal_name, journal_config, days_back, existing_paper_ids)
            all_new_papers.extend(papers)
            journal_stats[journal_name] = len(papers)
        
        # 中文期刊状态
        print("\n[2/2] 获取中文期刊论文...")
        for cn_name, cn_config in CN_JOURNALS.items():
            papers = self.fetch_journal_papers(cn_name, cn_config, days_back=days_back, existing_paper_ids=existing_paper_ids)
            for p in papers:
                p["language"] = "cn"
            all_new_papers.extend(papers)
            journal_stats[cn_name] = len(papers)
        
        print("\n[3/3] 获取计算机视觉和模式识别...")
        for cv_name, cv_config in CV_JOURNALS.items():
            papers = self.fetch_arxiv_recent_papers(cv_name, cv_config, existing_paper_ids)
            all_new_papers.extend(papers)
            journal_stats[cv_name] = len(papers)
        
        merged_papers = self.merge_papers(existing_papers, all_new_papers)

        # 如果有新增论文，先补充新论文的摘要
        if all_new_papers:
            print(f"\n[摘要补充] 为 {len(all_new_papers)} 篇新论文补充摘要...")
            for paper in all_new_papers:
                if not paper.get("abstract") or paper["abstract"] == "暂无摘要":
                    abstract = self.get_best_effort_abstract(
                        doi=paper.get("doi", ""),
                        page_url=paper.get("url", "")
                    )
                    if abstract:
                        paper["abstract"] = abstract

        # 如果指定了 backfill，对所有已有论文补充摘要
        if backfill:
            merged_papers = self.backfill_abstracts(merged_papers)

        self.sync_database(merged_papers)
        self.export_knowledge_base(merged_papers)
        
        output_data = {
            "papers": merged_papers,
            "last_update": datetime.now().isoformat(),
            "journals": {
                name: {"count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                for name in JOURNALS.keys()
            },
            "cn_journals": CN_JOURNALS,
            "cv_journals": {
                name: {"count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                for name in CV_JOURNALS.keys()
            },
            "source_groups": {
                "en": {
                    "title": "英文期刊",
                    "sources": [
                        {"name": name, "count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                        for name in JOURNALS.keys()
                    ]
                },
                "cn": {
                    "title": "中国期刊",
                    "sources": [
                        {"name": name, "count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                        for name in CN_JOURNALS.keys()
                    ]
                },
                "cv": {
                    "title": "计算机视觉和模式识别",
                    "sources": [
                        {"name": name, "count": sum(1 for p in merged_papers if p.get("journal_source") == name)}
                        for name in CV_JOURNALS.keys()
                    ]
                }
            },
            "stats": {
                "total": len(merged_papers),
                "new_added": len(all_new_papers),
                "by_journal": journal_stats,
                "by_language": {
                    "en": sum(1 for p in merged_papers if p.get("language") == "en"),
                    "cn": sum(1 for p in merged_papers if p.get("language") == "cn"),
                    "cv": sum(1 for p in merged_papers if p.get("journal_source") in CV_JOURNALS)
                }
            },
            "storage": {
                "database": self.db_file,
                "knowledge_base": self.kb_file
            }
        }
        
        os.makedirs(self.data_dir, exist_ok=True)
        with open(self.data_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        state["last_fetch"] = {
            name: datetime.now().isoformat()
            for name in list(JOURNALS.keys()) + list(CN_JOURNALS.keys()) + list(CV_JOURNALS.keys())
        }
        state["total_papers"] = len(merged_papers)
        state["storage"] = {
            "database": self.db_file,
            "knowledge_base": self.kb_file
        }
        state["last_run_stats"] = {
            "days_back": days_back,
            "new_added": len(all_new_papers),
            "total_papers": len(merged_papers)
        }
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--days-back", type=int, default=365)
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--backfill", action="store_true", help="对所有已有论文补充缺失的摘要")
    args = parser.parse_args()
    crawler = OpenAlexCrawler()
    if args.query.strip():
        results = crawler.search_knowledge_base(args.query, limit=args.limit)
        print(json.dumps({
            "query": args.query,
            "count": len(results),
            "results": results
        }, ensure_ascii=False, indent=2))
        return results
    data = crawler.run(days_back=args.days_back, backfill=args.backfill)
    return data


if __name__ == "__main__":
    main()
