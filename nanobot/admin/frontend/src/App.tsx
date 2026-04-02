import { useState } from "react";
import { BrowserRouter, Routes, Route, useNavigate } from "react-router-dom";
import Nav from "./components/Nav";
import TokenGate from "./components/TokenGate";
import DocumentList from "./pages/DocumentList";
import Upload from "./pages/Upload";
import Stats from "./pages/Stats";

function AppContent() {
  const navigate = useNavigate();

  const handleLogout = () => {
    navigate("/");
    window.location.reload();
  };

  return (
    <div style={{ minHeight: "100vh", background: "#f9fafb" }}>
      <Nav onLogout={handleLogout} />
      <Routes>
        <Route path="/" element={<DocumentList />} />
        <Route path="/upload" element={<Upload />} />
        <Route path="/stats" element={<Stats />} />
      </Routes>
    </div>
  );
}

function TokenGateWrapper() {
  const [ready, setReady] = useState(false);
  return ready ? <AppContent /> : <TokenGate onTokenSet={() => setReady(true)} />;
}

export default function App() {
  return (
    <BrowserRouter>
      <TokenGateWrapper />
    </BrowserRouter>
  );
}
