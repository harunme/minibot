import { ReactNode } from "react";

interface Props {
  title: string;
  message: ReactNode;
  onConfirm: () => void;
  onCancel: () => void;
  confirmText?: string;
  danger?: boolean;
}

export default function ConfirmDialog({
  title,
  message,
  onConfirm,
  onCancel,
  confirmText = "确认",
  danger = false,
}: Props) {
  return (
    <div style={styles.overlay} onClick={onCancel}>
      <div style={styles.dialog} onClick={e => e.stopPropagation()}>
        <h3 style={styles.title}>{title}</h3>
        <div style={styles.message}>{message}</div>
        <div style={styles.actions}>
          <button style={styles.cancel} onClick={onCancel}>取消</button>
          <button
            style={{
              ...styles.confirm,
              background: danger ? "#ef4444" : "#4f46e5",
            }}
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  overlay: {
    position: "fixed",
    inset: 0,
    background: "rgba(0,0,0,0.45)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  dialog: {
    background: "#fff",
    borderRadius: 12,
    padding: "24px",
    width: 360,
    boxShadow: "0 8px 32px rgba(0,0,0,0.2)",
  },
  title: {
    margin: "0 0 12px",
    fontSize: 16,
    fontWeight: 600,
    color: "#1a1a2e",
  },
  message: {
    fontSize: 14,
    color: "#555",
    marginBottom: 20,
    lineHeight: 1.5,
  },
  actions: {
    display: "flex",
    gap: 8,
    justifyContent: "flex-end",
  },
  cancel: {
    padding: "8px 16px",
    fontSize: 14,
    background: "#f3f4f6",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
    color: "#333",
  },
  confirm: {
    padding: "8px 16px",
    fontSize: 14,
    fontWeight: 600,
    color: "#fff",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
  },
};
