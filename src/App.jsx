import React, { useState, useMemo, useEffect } from 'react';
import './styles.css';

const DEFAULT_SOURCE_GROUPS = [
  {
    key: 'en',
    title: '英文期刊',
    sources: [
      { name: 'Information Processing in Agriculture', count: 0 },
      { name: 'Smart Agricultural Technology', count: 0 },
      { name: 'Artificial Intelligence in Agriculture', count: 0 },
      { name: 'Computers and Electronics in Agriculture', count: 0 },
      { name: 'Biosystems Engineering', count: 0 }
    ]
  },
  {
    key: 'cn',
    title: '中国期刊',
    sources: [
      { name: '农业工程学报', count: 0 },
      { name: '农业机械学报', count: 0 }
    ]
  },
  {
    key: 'cv',
    title: '计算机视觉和模式识别',
    sources: [
      { name: 'arXiv cs.CV Recent', count: 0 }
    ]
  }
];

const isChineseText = (text = '') => /[\u4e00-\u9fa5]/.test(text);

const getPaperAuthors = (paper) => {
  if (Array.isArray(paper?.authors) && paper.authors.length > 0) {
    return paper.authors;
  }
  if (typeof paper?.authors === 'string' && paper.authors.trim()) {
    return [paper.authors.trim()];
  }
  return ['Unknown'];
};

const getPaperKeywords = (paper) => {
  if (Array.isArray(paper?.keywords)) {
    return paper.keywords;
  }
  return [];
};

const getTranslatedTitle = (paper) => {
  const translatedTitle = paper?.translated_title || paper?.title_zh || '';
  if (!translatedTitle || translatedTitle === paper?.title) {
    return '';
  }
  return translatedTitle;
};

function App() {
  const [data, setData] = useState({ papers: [], journals: {}, cn_journals: {}, cv_journals: {}, source_groups: {}, last_update: null });
  const [loading, setLoading] = useState(true);
  const [activeJournal, setActiveJournal] = useState("Information Processing in Agriculture");
  const [showUnreadOnly, setShowUnreadOnly] = useState(false);
  const [papers, setPapers] = useState([]);
  const [expandedGroups, setExpandedGroups] = useState({ en: true, cn: true, cv: true, all: true });
  const [selectedPaper, setSelectedPaper] = useState(null);
  
  // 翻译状态
  const [translations, setTranslations] = useState({});
  const [translating, setTranslating] = useState(new Set());



  // 交互状态：已读和收藏 (持久化到 localStorage)
  const [readPapers, setReadPapers] = useState(() => {
    const saved = localStorage.getItem('bohrium_read_papers');
    return saved ? new Set(JSON.parse(saved)) : new Set();
  });
  
  const [starredPapers, setStarredPapers] = useState(() => {
    const saved = localStorage.getItem('bohrium_starred_papers');
    return saved ? new Set(JSON.parse(saved)) : new Set();
  });

  const [searchQuery, setSearchQuery] = useState("");

  // 无限滚动状态
  const [visibleCount, setVisibleCount] = useState(20);

  // 保存到 localStorage
  useEffect(() => {
    localStorage.setItem('bohrium_read_papers', JSON.stringify(Array.from(readPapers)));
  }, [readPapers]);

  useEffect(() => {
    localStorage.setItem('bohrium_starred_papers', JSON.stringify(Array.from(starredPapers)));
  }, [starredPapers]);

  // 动态加载数据
  useEffect(() => {
    // 强制每次加载不使用缓存，防止 vite 缓存静态文件
    fetch(`/papers.json?t=${new Date().getTime()}`)
      .then(res => res.json())
      .then(json => {
        setData(json);
        setPapers(json.papers || []);
        setLoading(false);
      })
      .catch(err => {
        console.error('加载数据失败:', err);
        setLoading(false);
      });
  }, []);

  const sourceGroups = useMemo(() => {
    const groupsFromData = Object.entries(data.source_groups || {})
      .map(([key, group]) => ({
        key,
        title: group.title,
        sources: (group.sources || []).map(source =>
          typeof source === 'string' ? { name: source, count: 0 } : source
        )
      }))
      .filter(group => group.sources.length > 0);

    return groupsFromData.length > 0 ? groupsFromData : DEFAULT_SOURCE_GROUPS;
  }, [data.source_groups]);

  const chineseJournalNames = useMemo(
    () => new Set((sourceGroups.find(group => group.key === 'cn')?.sources || []).map(source => source.name)),
    [sourceGroups]
  );

  const totalSubscribedSources = useMemo(
    () => sourceGroups.reduce((sum, group) => sum + group.sources.length, 0),
    [sourceGroups]
  );

  useEffect(() => {
    if (loading) return;
    if (activeJournal === '全部' || activeJournal === '已收藏') return;
    const validJournals = new Set(
      sourceGroups.flatMap(group => group.sources.map(source => source.name))
    );
    if (!validJournals.has(activeJournal)) {
      setActiveJournal(sourceGroups[0]?.sources[0]?.name || '全部');
    }
  }, [activeJournal, loading, sourceGroups]);

  const toggleGroup = (group) => {
    setExpandedGroups(prev => ({ ...prev, [group]: !prev[group] }));
  };

  const filteredPapers = useMemo(() => {
    let filtered = papers;
    // 模拟数据展示，如果数据为空，我们提供一些假数据以便看到界面效果
    if (filtered.length === 0 && !loading) {
      // 真实环境下如果确实没数据，不应显示旧的 mock 数据，而是直接返回空，或者明确提示无数据。
      // 这里如果需要 mock 数据展示排版，可以保留，但为了验证真实数据，我们将其暂时注释掉。
      /*
      filtered = [
        ...
      ];
      */
    }

    // 过滤逻辑
    if (activeJournal === "已收藏") {
      filtered = filtered.filter(p => starredPapers.has(p.id));
    } else if (activeJournal !== "全部") {
      filtered = filtered.filter(p => p.journal_source === activeJournal);
    }

    if (showUnreadOnly) {
      filtered = filtered.filter(p => !readPapers.has(p.id));
    }
    
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(p => 
        (p.title && p.title.toLowerCase().includes(q)) || 
        (p.abstract && p.abstract.toLowerCase().includes(q)) ||
        getPaperAuthors(p).some(a => a.toLowerCase().includes(q)) ||
        (p.journal_source && p.journal_source.toLowerCase().includes(q)) ||
        getPaperKeywords(p).some(k => k.toLowerCase().includes(q))
      );
    }
    
    return filtered;
  }, [papers, activeJournal, showUnreadOnly, loading, readPapers, starredPapers, searchQuery]);

  const activeJournalMeta = useMemo(() => {
    const activeGroup = sourceGroups.find(group =>
      group.sources.some(source => source.name === activeJournal)
    );
    const activeSource = activeGroup?.sources.find(source => source.name === activeJournal);
    return {
      title: activeGroup?.title || '全部来源',
      count: activeSource?.count ?? filteredPapers.length
    };
  }, [activeJournal, filteredPapers.length, sourceGroups]);


  // 自动翻译缓存状态 (持久化)
  const [autoTranslations, setAutoTranslations] = useState(() => {
    try {
      const saved = localStorage.getItem('bohrium_auto_translations');
      return saved ? JSON.parse(saved) : {};
    } catch (e) {
      console.error('Failed to parse autoTranslations', e);
      return {};
    }
  });

  useEffect(() => {
    localStorage.setItem('bohrium_auto_translations', JSON.stringify(autoTranslations));
  }, [autoTranslations]);

  // 翻译队列和执行
  useEffect(() => {
    if (loading) return;
    
    // 获取当前屏幕上显示的、且还没有翻译的英文论文
    const visiblePapers = filteredPapers.slice(0, visibleCount);
    const papersToTranslate = visiblePapers.filter(p => 
      !isChineseText(p.title) && 
      !getTranslatedTitle(p) && 
      !autoTranslations[p.id]
    );

    if (papersToTranslate.length === 0) return;

    let isMounted = true;
    let queue = [...papersToTranslate];

    const processQueue = async () => {
      while (queue.length > 0 && isMounted) {
        const paper = queue.shift();
        if (autoTranslations[paper.id]) continue; // 已经翻译过了
        
        try {
          // 先尝试 Google API
          const res = await fetch(`https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=${encodeURIComponent(paper.title)}`);
          if (res.ok) {
            const data = await res.json();
            let translated = '';
            if (data && data[0]) {
              data[0].forEach(item => {
                if (item[0]) translated += item[0];
              });
            }
            if (translated && isMounted) {
              setAutoTranslations(prev => ({ ...prev, [paper.id]: translated }));
              await new Promise(r => setTimeout(r, 500)); // 避免请求过快
              continue;
            }
          }
        } catch (err) {
          console.warn('Google Translate API fallback for:', paper.id);
        }

        // 如果 Google 失败，尝试 MyMemory
        try {
          const res = await fetch(`https://api.mymemory.translated.net/get?q=${encodeURIComponent(paper.title)}&langpair=en|zh-CN&de=developer@example.com`);
          if (res.ok) {
            const data = await res.json();
            if (data && data.responseData && data.responseData.translatedText) {
              if (isMounted) {
                setAutoTranslations(prev => ({ ...prev, [paper.id]: data.responseData.translatedText }));
                await new Promise(r => setTimeout(r, 1000)); // MyMemory 需要更长延迟
              }
            }
          }
        } catch (err) {
          console.error('Translation failed for:', paper.id, err);
        }
      }
    };

    processQueue();

    return () => {
      isMounted = false; // 组件卸载时停止队列
    };
  }, [filteredPapers, visibleCount, loading, autoTranslations]);

  // 当切换分类或仅看未读时，重置可见数量并滚动回顶部
  useEffect(() => {
    setVisibleCount(20);
    const listEl = document.querySelector('.paper-list');
    if (listEl) {
      listEl.scrollTop = 0;
    }
  }, [activeJournal, showUnreadOnly]);

  const handleScroll = (e) => {
    const bottom = e.target.scrollHeight - e.target.scrollTop <= e.target.clientHeight + 200;
    if (bottom && visibleCount < filteredPapers.length) {
      setVisibleCount(prev => prev + 20);
    }
  };

  const handlePaperClick = (paper) => {
    setSelectedPaper(paper);
    // 标记为已读
    if (!readPapers.has(paper.id)) {
      setReadPapers(prev => {
        const next = new Set(prev);
        next.add(paper.id);
        return next;
      });
    }
  };

  const toggleStar = (e, paperId) => {
    e.stopPropagation();
    setStarredPapers(prev => {
      const next = new Set(prev);
      if (next.has(paperId)) next.delete(paperId);
      else next.add(paperId);
      return next;
    });
  };

  const handleTranslate = async (e, paper) => {
    e.stopPropagation();
    
    if (translations[paper.id]) {
      setTranslations(prev => ({
        ...prev,
        [paper.id]: {
          ...prev[paper.id],
          show: !prev[paper.id].show
        }
      }));
      return;
    }

    setTranslating(prev => {
      const next = new Set(prev);
      next.add(paper.id);
      return next;
    });

    try {
      let translatedTitle = paper.translated_title || paper.title_zh || autoTranslations[paper.id] || paper.title;
      let translatedAbstract = paper.translated_abstract || paper.abstract || '暂无摘要';

      // 如果还没有被翻译过，调用真实 API 翻译摘要
      if (!paper.translated_abstract && paper.abstract && paper.abstract !== '暂无摘要') {
        try {
          // 因为摘要可能很长，我们使用 Google API
          const res = await fetch(`https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=zh-CN&dt=t&q=${encodeURIComponent(paper.abstract.substring(0, 4000))}`);
          if (res.ok) {
            const data = await res.json();
            let transText = '';
            if (data && data[0]) {
              data[0].forEach(item => {
                if (item[0]) transText += item[0];
              });
            }
            if (transText) {
              translatedAbstract = transText;
            }
          }
        } catch (err) {
          console.warn('Google API for abstract failed, fallback to MyMemory', err);
          try {
            // MyMemory 限制 500 个字符左右
            const res = await fetch(`https://api.mymemory.translated.net/get?q=${encodeURIComponent(paper.abstract.substring(0, 450))}&langpair=en|zh-CN&de=developer@example.com`);
            if (res.ok) {
              const data = await res.json();
              if (data?.responseData?.translatedText) {
                translatedAbstract = data.responseData.translatedText + '... (受限于免费API，仅翻译部分摘要)';
              }
            }
          } catch (e) {}
        }
      }

      setTranslations(prev => ({
        ...prev,
        [paper.id]: {
          title: translatedTitle,
          abstract: translatedAbstract,
          show: true
        }
      }));
    } finally {
      setTranslating(prev => {
        const next = new Set(prev);
        next.delete(paper.id);
        return next;
      });
    }
  };

  // 获取某个分类下的未读数量
  const getUnreadCount = (journalName) => {
    let list = papers;
    if (journalName !== '全部') {
      list = list.filter(p => p.journal_source === journalName);
    }
    return list.filter(p => !readPapers.has(p.id)).length;
  };

  const markAllAsRead = () => {
    setReadPapers(prev => {
      const next = new Set(prev);
      filteredPapers.forEach(p => next.add(p.id));
      return next;
    });
  };

  const getPaperLinkLabel = (paper) => {
    if (!paper?.url) return '';
    if (paper.url.includes('openalex.org')) return '在 OpenAlex 中查看';
    if (paper.url.includes('arxiv.org')) return '查看 arXiv';
    return '查看原文';
  };

  const renderSidebar = () => (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div>
          <h2 className="sidebar-title">订阅</h2>
          <p className="sidebar-subtitle">农业领域文献追踪</p>
        </div>
      </div>

      <div className="sidebar-menu">
        <div className={`menu-item ${activeJournal === '全部' ? 'active' : ''}`} onClick={() => setActiveJournal('全部')}>
          <span className="menu-text">所有订阅</span>
          {getUnreadCount('全部') > 0 && <span className="unread-count">{getUnreadCount('全部')}</span>}
        </div>

        <div className={`menu-item ${activeJournal === '已收藏' ? 'active' : ''}`} onClick={() => setActiveJournal('已收藏')}>
          <span className="menu-text">已收藏</span>
          <span className="unread-count">{starredPapers.size}</span>
        </div>

        <div className="menu-group">
          <div className="menu-group-header" onClick={() => toggleGroup('all')}>
            <span className={`collapse-icon ${expandedGroups.all ? 'open' : ''}`}>▶</span>
            <span className="menu-text bold">期刊订阅 ({totalSubscribedSources})</span>
          </div>
          
          {expandedGroups.all && (
            <div className="menu-sub-groups">
              {sourceGroups.map(group => (
                <div className="menu-group" key={group.key}>
                  <div className="menu-group-header sub" onClick={() => toggleGroup(group.key)}>
                    <span className={`collapse-icon ${expandedGroups[group.key] ? 'open' : ''}`}>▶</span>
                    <span className="menu-text">{group.title} ({group.sources.length})</span>
                  </div>
                  {expandedGroups[group.key] && (
                    <div className="menu-list">
                      {group.sources.map(source => {
                        const unread = getUnreadCount(source.name);
                        const iconType = group.key === 'cn' ? 'cn' : 'en';
                        return (
                          <div 
                            key={source.name} 
                            className={`menu-item journal ${activeJournal === source.name ? 'active' : ''}`}
                            onClick={() => setActiveJournal(source.name)}
                          >
                            <div className={`journal-icon-placeholder ${iconType}`}>
                              {source.name.charAt(0).toUpperCase()}
                            </div>
                            <span className="menu-text wrap" title={source.name}>{source.name}</span>
                            {unread > 0 && <span className="unread-dot"></span>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </aside>
  );

  const renderMainContent = () => (
    <main className="main-content">
      {/* 顶部控制栏 */}
      <header className="content-header">
        <div className="header-left">
          <div className="current-journal">
            <div className={`journal-icon-placeholder large ${chineseJournalNames.has(activeJournal) ? 'cn' : 'en'}`}>
              {activeJournal !== '全部' && activeJournal !== '已收藏' ? activeJournal.charAt(0).toUpperCase() : (activeJournal === '全部' ? 'A' : 'S')}
            </div>
            <div className="current-journal-info">
              <h1 className="journal-title wrap">{activeJournal}</h1>
              <p className="journal-subtitle">
                {activeJournalMeta.title} · 当前 {filteredPapers.length} 篇
                {activeJournal !== '全部' && activeJournal !== '已收藏' && activeJournalMeta.count !== filteredPapers.length
                  ? ` / 总计 ${activeJournalMeta.count} 篇`
                  : ''}
              </p>
            </div>
          </div>
          <label className="toggle-switch">
            <input 
              type="checkbox" 
              checked={showUnreadOnly} 
              onChange={(e) => setShowUnreadOnly(e.target.checked)} 
            />
            <span className="toggle-slider"></span>
            <span className="toggle-label">仅看未读</span>
          </label>
        </div>
        <div className="header-right">
          <div className="search-box">
            <span className="search-icon">🔍</span>
            <input 
              type="text" 
              placeholder="搜索标题、作者、摘要..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
          <button className="action-btn" onClick={markAllAsRead}><span>✔️</span> 全部已读</button>
        </div>
      </header>

      {/* AI速览 */}
      <div className="ai-overview-section">
        <button className="ai-overview-btn">
          <span className="ai-icon">✨</span> AI 速览
        </button>
        <p className="update-text">
          当前列表共 {filteredPapers.length} 篇论文
          {data.last_update ? ` · 最近同步 ${new Date(data.last_update).toLocaleString('zh-CN')}` : ''}
        </p>
      </div>

      {/* 论文列表 */}
      <div className="paper-list" onScroll={handleScroll}>
        {loading ? (
          // 加载状态骨架屏
          Array.from({ length: 5 }).map((_, i) => (
            <div key={`sk-${i}`} className="skeleton-card">
              <div className="skeleton-line title"></div>
              <div className="skeleton-line authors"></div>
              <div className="skeleton-line meta"></div>
              <div className="skeleton-line text"></div>
              <div className="skeleton-line text" style={{width: '80%'}}></div>
            </div>
          ))
        ) : filteredPapers.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 40px', color: '#999' }}>
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>📭</div>
            {searchQuery ? `未找到与 "${searchQuery}" 相关的文献。` : '该分类下暂无相关文献数据。'}
          </div>
        ) : (
          filteredPapers.slice(0, visibleCount).map(paper => (
            <div 
              key={paper.id} 
              className={`paper-card ${readPapers.has(paper.id) ? 'is-read' : ''}`}
              onClick={() => handlePaperClick(paper)}
              style={{ cursor: 'pointer' }}
            >
              <button 
                className={`star-btn ${starredPapers.has(paper.id) ? 'active' : ''}`}
                onClick={(e) => toggleStar(e, paper.id)}
                title={starredPapers.has(paper.id) ? "取消收藏" : "收藏"}
              >
                {starredPapers.has(paper.id) ? '★' : '☆'}
              </button>
              { chineseJournalNames.has(paper.journal_source) ? (
              <h2 className="paper-title-zh-main">{paper.title}</h2>
            ) : (
              <>
                <h2 className="paper-title-en">{translations[paper.id]?.show ? translations[paper.id].title : paper.title}</h2>
                { !isChineseText(paper.title) && (getTranslatedTitle(paper) || autoTranslations[paper.id]) && !translations[paper.id]?.show && (
                  <h3 className="paper-title-zh">{getTranslatedTitle(paper) || autoTranslations[paper.id]}</h3>
                )}
              </>
            )}
            
            <div className="paper-authors">
              {getPaperAuthors(paper).map((author, idx) => (
                <div key={idx} className="author-badge">
                  <span className="author-name">{author}</span>
                </div>
              ))}
            </div>

            <div className="paper-meta">
              <span className="meta-date">发布时间: {paper.date}</span>
              <div className="meta-journal">
                <span className="journal-name">来源: {paper.journal_source || paper.journal}</span>
                <span className="impact-factor">
                  {paper.doi && <a href={paper.doi} target="_blank" rel="noreferrer" style={{marginLeft: 10, color: '#4f46e5'}}>DOI 链接</a>}
                </span>
              </div>
            </div>

            <div className="paper-abstract">
              {paper.abstract && paper.abstract !== "暂无摘要" ? (
                <>
                  <span style={{fontWeight: 600}}>摘要：</span>
                  {translations[paper.id]?.show
                    ? (translations[paper.id].abstract.length > 300 ? translations[paper.id].abstract.substring(0, 300) + '...' : translations[paper.id].abstract)
                    : (paper.abstract.length > 300 ? paper.abstract.substring(0, 300) + '...' : paper.abstract)}
                </>
              ) : (
                <div className="no-abstract-hint">
                  <span className="no-abstract-icon">📄</span>
                  <span>该文献暂未提供摘要信息</span>
                  {paper.doi && (
                    <a
                      href={paper.doi}
                      target="_blank"
                      rel="noreferrer"
                      className="no-abstract-link"
                      onClick={(e) => e.stopPropagation()}
                    >
                      在出版商网站查看 →
                    </a>
                  )}
                </div>
              )}
            </div>

            <div className="paper-footer">
              <div className="paper-stats">
                <span className="stat-item">⏱ 1.2K</span>
                <span className="stat-item">💬 66</span>
                <span className="stat-item">🔖 {paper.cited_by_count || 0}</span>
                {paper.open_access && <span className="oa-badge">OA</span>}
              </div>
              <div className="paper-actions">
                { !chineseJournalNames.has(paper.journal_source) && (
                  <button
                    className="icon-action-btn"
                    onClick={(e) => handleTranslate(e, paper)}
                    disabled={translating.has(paper.id)}
                  >
                    {translating.has(paper.id) ? '⏳ 翻译中...' : (translations[paper.id]?.show ? '🇨🇳 显示原文' : '🇺🇸 翻译')}
                  </button>
                )}
                {paper.url && (
                  <button className="icon-action-btn" onClick={(e) => { e.stopPropagation(); window.open(paper.url, '_blank'); }}>
                    ↗️ 打开
                  </button>
                )}
                {(!paper.abstract || paper.abstract === "暂无摘要") && paper.doi && (
                  <button
                    className="action-btn primary small"
                    onClick={(e) => { e.stopPropagation(); window.open(paper.doi, '_blank'); }}
                    title="在出版商网站查看摘要"
                  >
                    📄 查看原文
                  </button>
                )}
                <button
                  className="action-btn collect"
                  onClick={(e) => toggleStar(e, paper.id)}
                >
                  <span>{starredPapers.has(paper.id) ? '★' : '➕'}</span>
                  {starredPapers.has(paper.id) ? '已收藏' : '收藏'}
                </button>
              </div>
            </div>
          </div>
        )))}
      </div>
    </main>
  );

  const renderDrawer = () => {
    if (!selectedPaper) return null;

    return (
      <div className="drawer-overlay" onClick={() => setSelectedPaper(null)}>
        <div className="drawer-content" onClick={(e) => e.stopPropagation()}>
          <div className="drawer-header">
            <h2 className="drawer-title">文献详情</h2>
            <button className="drawer-close" onClick={() => setSelectedPaper(null)}>×</button>
          </div>
          
          <div className="drawer-body">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
              <h1 className="detail-title" style={{ marginBottom: 0 }}>
                {translations[selectedPaper.id]?.show ? translations[selectedPaper.id].title : selectedPaper.title}
              </h1>
              {!chineseJournalNames.has(selectedPaper.journal_source) && (
                <button 
                  className="icon-action-btn" 
                  onClick={(e) => handleTranslate(e, selectedPaper)}
                  disabled={translating.has(selectedPaper.id)}
                  style={{ flexShrink: 0, marginLeft: 16 }}
                >
                  {translating.has(selectedPaper.id) ? '⏳ 翻译中...' : (translations[selectedPaper.id]?.show ? '🇨🇳 显示原文' : '🇺🇸 翻译')}
                </button>
              )}
            </div>
            
            { !chineseJournalNames.has(selectedPaper.journal_source) && !isChineseText(selectedPaper.title) && (getTranslatedTitle(selectedPaper) || autoTranslations[selectedPaper.id]) && !translations[selectedPaper.id]?.show && (
              <h2 className="detail-title-zh">{getTranslatedTitle(selectedPaper) || autoTranslations[selectedPaper.id]}</h2>
            )}

            <div className="detail-authors">
              {getPaperAuthors(selectedPaper).map((author, idx) => (
                <span key={idx} className="detail-author">{author}</span>
              ))}
            </div>

            <div className="detail-meta-box">
              <div className="detail-meta-item">
                <span className="meta-label">来源期刊</span>
                <span className="meta-value">{selectedPaper.journal_source || selectedPaper.journal}</span>
              </div>
              <div className="detail-meta-item">
                <span className="meta-label">发布日期</span>
                <span className="meta-value">{selectedPaper.date}</span>
              </div>
              <div className="detail-meta-item">
                <span className="meta-label">DOI</span>
                <span className="meta-value">
                  {selectedPaper.doi ? (
                    <a href={selectedPaper.doi} target="_blank" rel="noreferrer" className="doi-link">
                      {selectedPaper.doi}
                    </a>
                  ) : "暂无"}
                </span>
              </div>
            </div>

            <div className="detail-section">
              <h3 className="section-title">摘要</h3>
              <div className="detail-abstract">
                {translations[selectedPaper.id]?.show 
                  ? translations[selectedPaper.id].abstract
                  : (selectedPaper.abstract && selectedPaper.abstract !== "暂无摘要" 
                    ? selectedPaper.abstract 
                    : "该文献暂未提供摘要信息。")}
              </div>
            </div>

            {getPaperKeywords(selectedPaper).length > 0 && (
              <div className="detail-section">
                <h3 className="section-title">关键词</h3>
                <div className="detail-keywords">
                  {getPaperKeywords(selectedPaper).map((kw, idx) => (
                    <span key={idx} className="keyword-tag">{kw}</span>
                  ))}
                </div>
              </div>
            )}

            <div className="detail-actions">
              <button 
                className="action-btn outline"
                onClick={(e) => toggleStar(e, selectedPaper.id)}
                style={{ color: starredPapers.has(selectedPaper.id) ? '#f59e0b' : '', borderColor: starredPapers.has(selectedPaper.id) ? '#f59e0b' : '' }}
              >
                {starredPapers.has(selectedPaper.id) ? '★ 已收藏' : '☆ 收藏'}
              </button>
              {selectedPaper.url && (
                <a href={selectedPaper.url} target="_blank" rel="noreferrer" className="action-btn primary">
                  {getPaperLinkLabel(selectedPaper)}
                </a>
              )}
              {selectedPaper.pdf_url && (
                <a href={selectedPaper.pdf_url} target="_blank" rel="noreferrer" className="action-btn outline">
                  PDF 链接
                </a>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="app-container">
      <div className="main-layout">
        {renderSidebar()}
        {renderMainContent()}
      </div>
      {renderDrawer()}
    </div>
  );
}

export default App;
