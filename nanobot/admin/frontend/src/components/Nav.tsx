import { Link, useLocation } from "react-router-dom";
import { clearToken } from "../api/client";

interface Props {
  onLogout: () => void;
}

export default function Nav({ onLogout }: Props) {
  const location = useLocation();

  const linkStyle = (path: string): React.CSSProperties => ({
    textDecoration: "none",
    fontSize: 14,
    fontWeight: location.pathname === path ? 600 : 400,
    color: location.pathname === path ? "#4f46e5" : "#555",
    padding: "6px 12px",
    borderRadius: 6,
    background: location.pathname === path ? "#eef2ff" : "transparent",
    transition: "all 0.15s",
  });

  return (
    <nav style={styles.nav}>
      <span style={styles.brand}>MiniBot 知识库</span>
      <div style={styles.links}>
        <Link to="/" style={linkStyle("/")}>文档列表</Link>
        <Link to="/upload" style={linkStyle("/upload")}>上传文档</Link>
        <Link to="/stats" style={linkStyle("/stats")}>统计</Link>
      </div>
      <button
        onClick={() => { clearToken(); onLogout(); }}
        style={styles.logout}
      >
        退出登录
      </button>
    </nav>
  );
}

const styles: Record<string, React.CSSProperties> = {
  nav: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    padding: "12px 24px",
    background: "#fff",
    borderBottom: "1px solid #e5e7eb",
    position: "sticky" as const,
    top: 0,
    zIndex: 100,
  },
  brand: {
    fontWeight: 700,
    fontSize: 16,
    color: "#1a1a2e",
    marginRight: 24,
  },
  links: {
    display: "flex",
    gap: 4,
    flex: 1,
  },
  logout: {
    marginLeft: "auto",
    padding: "6px 14px",
    fontSize: 13,
    background: "transparent",
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    cursor: "pointer",
    color: "#666",
  },
};
