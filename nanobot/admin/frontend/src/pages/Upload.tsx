import { useRef, useState } from "react";
import { api, UploadResponse } from "../api/client";

export default function Upload() {
  const [dragging, setDragging] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [category, setCategory] = useState("");
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) setSelectedFile(file);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setSelectedFile(file);
    setResult(null);
    setError(null);
  };

  const handleUpload = async () => {
    if (!selectedFile) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.uploadDocument(selectedFile, category || "general");
      setResult(res);
      setSelectedFile(null);
      if (inputRef.current) inputRef.current.value = "";
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div style={styles.page}>
      <h2 style={styles.h2}>上传文档</h2>

      {/* Drop Zone */}
      <div
        style={{
          ...styles.dropZone,
          borderColor: dragging ? "#4f46e5" : selectedFile ? "#4f46e5" : "#d1d5db",
          background: dragging ? "#eef2ff" : "#fff",
        }}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.txt,.md"
          style={{ display: "none" }}
          onChange={handleFileChange}
        />
        {selectedFile ? (
          <div style={styles.filePreview}>
            <span style={styles.fileIcon}>📄</span>
            <div>
              <div style={styles.fileName}>{selectedFile.name}</div>
              <div style={styles.fileSize}>
                {(selectedFile.size / 1024).toFixed(1)} KB
              </div>
            </div>
            <button
              style={styles.removeBtn}
              onClick={e => { e.stopPropagation(); setSelectedFile(null); }}
            >
              ✕
            </button>
          </div>
        ) : (
          <div style={styles.dropText}>
            <div style={styles.dropIcon}>📂</div>
            <div>拖拽文件到这里，或点击选择文件</div>
            <div style={styles.dropHint}>支持 PDF、TXT、MD 格式</div>
          </div>
        )}
      </div>

      {/* Category */}
      <div style={styles.field}>
        <label style={styles.label}>文档分类</label>
        <input
          style={styles.input}
          placeholder="例如：故事、唐诗、绘本（可选）"
          value={category}
          onChange={e => setCategory(e.target.value)}
        />
      </div>

      {/* Upload Button */}
      <button
        style={{
          ...styles.uploadBtn,
          opacity: uploading || !selectedFile ? 0.6 : 1,
        }}
        disabled={uploading || !selectedFile}
        onClick={handleUpload}
      >
        {uploading ? "上传中..." : "开始入库"}
      </button>

      {error && <div style={styles.error}>{error}</div>}

      {result && (
        <div style={styles.success}>
          <div style={styles.successTitle}>入库成功！</div>
          <div>文件名：{result.file_name}</div>
          <div>总页数：{result.total_pages}</div>
          <div>创建块数：{result.chunks_created}</div>
          <div style={styles.docIds}>块 IDs：{result.doc_ids.slice(0, 3).join(", ")}
            {result.doc_ids.length > 3 ? "..." : ""}
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: 24 },
  h2: { margin: "0 0 20px", fontSize: 20, fontWeight: 600 },
  dropZone: {
    border: "2px dashed",
    borderRadius: 12,
    padding: 40,
    textAlign: "center" as const,
    cursor: "pointer",
    transition: "all 0.15s",
    marginBottom: 20,
  },
  dropText: { color: "#888" },
  dropIcon: { fontSize: 36, marginBottom: 8 },
  dropHint: { fontSize: 13, marginTop: 4, color: "#aaa" },
  filePreview: {
    display: "flex", alignItems: "center", gap: 12,
    textAlign: "left" as const, justifyContent: "center",
  },
  fileIcon: { fontSize: 28 },
  fileName: { fontSize: 15, fontWeight: 600, color: "#1a1a2e" },
  fileSize: { fontSize: 13, color: "#888" },
  removeBtn: {
    marginLeft: "auto", background: "none", border: "none",
    fontSize: 16, cursor: "pointer", color: "#999",
  },
  field: { marginBottom: 16 },
  label: { display: "block", fontSize: 14, fontWeight: 500, marginBottom: 6, color: "#333" },
  input: {
    width: "100%", padding: "9px 12px", fontSize: 14, border: "1.5px solid #e5e7eb",
    borderRadius: 8, outline: "none", boxSizing: "border-box" as const,
  },
  uploadBtn: {
    width: "100%", padding: "11px 0", fontSize: 15, fontWeight: 600,
    background: "#4f46e5", color: "#fff", border: "none", borderRadius: 8,
    cursor: "pointer",
  },
  error: { marginTop: 16, padding: "12px 16px", background: "#fef2f2", color: "#dc2626", borderRadius: 8, fontSize: 14 },
  success: { marginTop: 16, padding: 16, background: "#f0fdf4", border: "1px solid #bbf7d0", borderRadius: 8, fontSize: 14, color: "#166534" },
  successTitle: { fontSize: 16, fontWeight: 600, marginBottom: 8 },
  docIds: { marginTop: 4, fontSize: 12, color: "#888", wordBreak: "break-all" as const },
};
