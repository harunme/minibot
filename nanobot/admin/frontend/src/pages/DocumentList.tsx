import { useCallback, useEffect, useRef, useState } from "react";
import { api, DocumentMeta } from "../api/client";
import ConfirmDialog from "../components/ConfirmDialog";

export default function DocumentList() {
  const [docs, setDocs] = useState<DocumentMeta[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [searchQ, setSearchQ] = useState("");
  const [searchResults, setSearchResults] = useState<typeof docs | null>(null);
  const [categoryFilter, setCategoryFilter] = useState("");
  const [categories, setCategories] = useState<string[]>([]);

  const [offset, setOffset] = useState(0);
  const [deleting, setDeleting] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [viewDoc, setViewDoc] = useState<{ id: string; content: string } | null>(null);

  const LIMIT = 20;
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadDocs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.listDocuments({
        category: categoryFilter || undefined,
        limit: LIMIT,
        offset,
      });
      setDocs(res.documents);
      setTotal(res.total);
      // 提取所有分类
      const cats = Array.from(new Set(
        res.documents.map(d => d.metadata.category).filter(Boolean) as string[]
      )).sort();
      setCategories(cats);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, offset]);

  useEffect(() => {
    loadDocs();
  }, [loadDocs]);

  // 防抖搜索
  const handleSearch = (q: string) => {
    setSearchQ(q);
    if (!q.trim()) {
      setSearchResults(null);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await api.search({ q, top_k: 20, category: categoryFilter || undefined });
        setSearchResults(res.results.map(r => ({
          id: r.id,
          content_preview: r.content.slice(0, 200) + (r.content.length > 200 ? "..." : ""),
          metadata: r.metadata,
        })));
      } catch {
        // ignore
      }
    }, 300);
  };

  const handleDelete = async (id: string) => {
    setDeleting(prev => [...prev, id]);
    try {
      await api.deleteDocument(id);
      setDocs(prev => prev.filter(d => d.id !== id));
      setTotal(prev => prev - 1);
    } catch (e) {
      alert(String(e));
    } finally {
      setDeleting(prev => prev.filter(x => x !== id));
      setConfirmDelete(null);
    }
  };

  const displayed = searchResults ?? docs;
  const currentTotal = searchResults ? searchResults.length : total;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h2 style={styles.h2}>
          {searchResults ? `搜索结果 (${searchResults.length})` : `文档列表 (${total})`}
        </h2>
      </div>

      <div style={styles.toolbar}>
        <input
          style={styles.searchInput}
          placeholder="搜索文档内容..."
          value={searchQ}
          onChange={e => handleSearch(e.target.value)}
        />
        <select
          style={styles.select}
          value={categoryFilter}
          onChange={e => {
            setCategoryFilter(e.target.value);
            setOffset(0);
            setSearchResults(null);
          }}
        >
          <option value="">全部分类</option>
          {categories.map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        {(searchResults || categoryFilter) && (
          <button
            style={styles.clearBtn}
            onClick={() => {
              setSearchResults(null);
              setSearchQ("");
              setCategoryFilter("");
              setOffset(0);
            }}
          >
            清除筛选
          </button>
        )}
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <div style={styles.center}>加载中...</div>
      ) : displayed.length === 0 ? (
        <div style={styles.center}>暂无文档，试试上传？</div>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr style={styles.tr}>
              <th style={styles.th}>来源</th>
              <th style={styles.th}>分类</th>
              <th style={styles.th}>内容预览</th>
              <th style={styles.th}>操作</th>
            </tr>
          </thead>
          <tbody>
            {displayed.map(doc => (
              <tr key={doc.id} style={styles.tr}>
                <td style={styles.td}>{doc.metadata.source || "—"}</td>
                <td style={styles.td}>
                  <span style={styles.badge}>{doc.metadata.category || "general"}</span>
                </td>
                <td style={{ ...styles.td, maxWidth: 360 }}>
                  <span title={doc.content_preview}>{doc.content_preview}</span>
                </td>
                <td style={styles.td}>
                  <button style={styles.actionBtn} onClick={() => api.getDocument(doc.id).then(d => setViewDoc(d))}>
                    查看
                  </button>
                  <button
                    style={{ ...styles.actionBtn, color: "#ef4444" }}
                    onClick={() => setConfirmDelete(doc.id)}
                    disabled={deleting.includes(doc.id)}
                  >
                    {deleting.includes(doc.id) ? "删除中..." : "删除"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {!searchResults && (
        <div style={styles.pagination}>
          <button disabled={offset === 0} onClick={() => setOffset(o => Math.max(0, o - LIMIT))}>
            上一页
          </button>
          <span>{offset + 1}–{Math.min(offset + LIMIT, currentTotal)} / {currentTotal}</span>
          <button disabled={offset + LIMIT >= currentTotal} onClick={() => setOffset(o => o + LIMIT)}>
            下一页
          </button>
        </div>
      )}

      {confirmDelete && (
        <ConfirmDialog
          title="确认删除"
          message={`删除后无法恢复，确定删除这篇文档？`}
          onConfirm={() => handleDelete(confirmDelete)}
          onCancel={() => setConfirmDelete(null)}
          confirmText="删除"
          danger
        />
      )}

      {viewDoc && (
        <div style={styles.overlay} onClick={() => setViewDoc(null)}>
          <div style={styles.previewPanel} onClick={e => e.stopPropagation()}>
            <div style={styles.previewHeader}>
              <h3 style={styles.previewTitle}>文档内容</h3>
              <button style={styles.closeBtn} onClick={() => setViewDoc(null)}>✕</button>
            </div>
            <div style={styles.previewContent}>{viewDoc.content}</div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: 24 },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 },
  h2: { margin: 0, fontSize: 20, fontWeight: 600 },
  toolbar: { display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" as const },
  searchInput: {
    flex: 1, minWidth: 200, padding: "8px 12px", fontSize: 14,
    border: "1.5px solid #e5e7eb", borderRadius: 8, outline: "none",
  },
  select: { padding: "8px 12px", fontSize: 14, border: "1.5px solid #e5e7eb", borderRadius: 8 },
  clearBtn: {
    padding: "8px 14px", fontSize: 13, background: "#f3f4f6", border: "none",
    borderRadius: 8, cursor: "pointer",
  },
  error: { padding: "12px 16px", background: "#fef2f2", color: "#dc2626", borderRadius: 8, marginBottom: 16 },
  center: { padding: 40, textAlign: "center" as const, color: "#999" },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 14 },
  tr: { borderBottom: "1px solid #f3f4f6" },
  th: { textAlign: "left", padding: "10px 12px", color: "#888", fontWeight: 500, whiteSpace: "nowrap" as const },
  td: { padding: "10px 12px", color: "#333", verticalAlign: "middle" as const },
  badge: {
    display: "inline-block", padding: "2px 8px", fontSize: 12,
    background: "#e0e7ff", color: "#4f46e5", borderRadius: 999,
  },
  actionBtn: {
    padding: "4px 10px", fontSize: 13, marginRight: 4, cursor: "pointer",
    background: "#f3f4f6", border: "none", borderRadius: 6,
  },
  pagination: {
    display: "flex", gap: 12, alignItems: "center", justifyContent: "center",
    marginTop: 20,
  },
  overlay: {
    position: "fixed", inset: 0, background: "rgba(0,0,0,0.45)",
    display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000,
  },
  previewPanel: {
    background: "#fff", borderRadius: 12, padding: 0, width: 600, maxHeight: "80vh",
    display: "flex", flexDirection: "column" as const, overflow: "hidden",
    boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
  },
  previewHeader: {
    display: "flex", alignItems: "center", justifyContent: "space-between",
    padding: "16px 20px", borderBottom: "1px solid #f3f4f6",
  },
  previewTitle: { margin: 0, fontSize: 16, fontWeight: 600 },
  closeBtn: {
    background: "none", border: "none", fontSize: 18, cursor: "pointer", color: "#999",
  },
  previewContent: {
    padding: 20, overflowY: "auto" as const, fontSize: 14, lineHeight: 1.7,
    whiteSpace: "pre-wrap" as const, flex: 1,
  },
};
