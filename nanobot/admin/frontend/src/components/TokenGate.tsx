import { getToken } from "../api/client";

interface Props {
  onTokenSet: () => void;
}

export default function TokenGate({ onTokenSet }: Props) {
  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const token = fd.get("token") as string;
    if (!token.trim()) return;
    sessionStorage.setItem("nanobot_admin_token", token.trim());
    onTokenSet();
  };

  if (getToken()) {
    onTokenSet();
    return null;
  }

  return (
    <div style={styles.container}>
      <div style={styles.card}>
        <h1 style={styles.title}>MiniBot 知识库管理</h1>
        <p style={styles.subtitle}>请输入管理后台访问令牌</p>
        <form onSubmit={handleSubmit} style={styles.form}>
          <input
            name="token"
            type="password"
            placeholder="Bearer Token"
            style={styles.input}
            autoFocus
          />
          <button type="submit" style={styles.button}>
            进入管理后台
          </button>
        </form>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minHeight: "100vh",
    background: "#f5f5f5",
  },
  card: {
    background: "#fff",
    borderRadius: 12,
    padding: "40px 32px",
    width: 360,
    boxShadow: "0 2px 12px rgba(0,0,0,0.1)",
    textAlign: "center" as const,
  },
  title: {
    fontSize: 22,
    fontWeight: 600,
    margin: "0 0 8px",
    color: "#1a1a2e",
  },
  subtitle: {
    fontSize: 14,
    color: "#666",
    margin: "0 0 28px",
  },
  form: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 12,
  },
  input: {
    padding: "10px 14px",
    fontSize: 15,
    border: "1.5px solid #ddd",
    borderRadius: 8,
    outline: "none",
    width: "100%",
    boxSizing: "border-box" as const,
  },
  button: {
    padding: "10px 14px",
    fontSize: 15,
    fontWeight: 600,
    background: "#4f46e5",
    color: "#fff",
    border: "none",
    borderRadius: 8,
    cursor: "pointer",
  },
};
