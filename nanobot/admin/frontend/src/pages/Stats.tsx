import { useEffect, useState } from "react";
import { api, CollectionStats } from "../api/client";

export default function Stats() {
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getStats();
      setStats(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const fmtBytes = (bytes: number | null): string => {
    if (bytes === null) return "—";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const maxCount = stats
    ? Math.max(...Object.values(stats.categories), 1)
    : 1;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h2 style={styles.h2}>知识库统计</h2>
        <button style={styles.reload} onClick={load} disabled={loading}>
          {loading ? "加载中..." : "刷新"}
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <div style={styles.center}>加载中...</div>
      ) : stats ? (
        <>
          <div style={styles.cards}>
            <div style={styles.card}>
              <div style={styles.cardValue}>{stats.count.toLocaleString()}</div>
              <div style={styles.cardLabel}>总文档块数</div>
            </div>
            <div style={styles.card}>
              <div style={styles.cardValue}>{Object.keys(stats.categories).length}</div>
              <div style={styles.cardLabel}>文档分类数</div>
            </div>
            <div style={styles.card}>
              <div style={styles.cardValue}>{fmtBytes(stats.storage_bytes)}</div>
              <div style={styles.cardLabel}>存储占用</div>
            </div>
          </div>

          {Object.keys(stats.categories).length > 0 && (
            <div style={styles.section}>
              <h3 style={styles.h3}>分类分布</h3>
              <div style={styles.barChart}>
                {Object.entries(stats.categories)
                  .sort((a, b) => b[1] - a[1])
                  .map(([cat, count]) => (
                    <div key={cat} style={styles.barRow}>
                      <span style={styles.barLabel}>{cat}</span>
                      <div style={styles.barTrack}>
                        <div
                          style={{
                            ...styles.barFill,
                            width: `${Math.round((count / maxCount) * 100)}%`,
                          }}
                        />
                      </div>
                      <span style={styles.barCount}>{count}</span>
                    </div>
                  ))}
              </div>
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: 24 },
  header: { display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 },
  h2: { margin: 0, fontSize: 20, fontWeight: 600 },
  reload: {
    padding: "8px 16px", fontSize: 14, background: "#f3f4f6",
    border: "none", borderRadius: 8, cursor: "pointer",
  },
  error: { padding: "12px 16px", background: "#fef2f2", color: "#dc2626", borderRadius: 8, marginBottom: 16 },
  center: { padding: 40, textAlign: "center" as const, color: "#999" },
  cards: { display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginBottom: 32 },
  card: {
    background: "#fff", borderRadius: 12, padding: 24,
    boxShadow: "0 1px 4px rgba(0,0,0,0.08)", textAlign: "center" as const,
  },
  cardValue: { fontSize: 32, fontWeight: 700, color: "#4f46e5" },
  cardLabel: { fontSize: 13, color: "#888", marginTop: 4 },
  section: { background: "#fff", borderRadius: 12, padding: 24, boxShadow: "0 1px 4px rgba(0,0,0,0.08)" },
  h3: { margin: "0 0 16px", fontSize: 16, fontWeight: 600 },
  barChart: { display: "flex", flexDirection: "column" as const, gap: 12 },
  barRow: { display: "flex", alignItems: "center", gap: 12 },
  barLabel: { width: 80, fontSize: 14, color: "#333", textAlign: "right" as const, flexShrink: 0 },
  barTrack: { flex: 1, height: 20, background: "#f3f4f6", borderRadius: 4, overflow: "hidden" },
  barFill: { height: "100%", background: "#6366f1", borderRadius: 4, minWidth: 4 },
  barCount: { width: 40, fontSize: 13, color: "#888", flexShrink: 0, textAlign: "right" as const },
};
