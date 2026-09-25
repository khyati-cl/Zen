import { useState, useEffect } from "react";
import ChatView from "./components/ChatView";
import Sidebar from "./components/Sidebar";
import AuthPage from "./components/AuthPage";
import "./App.css";

const API = "http://localhost:8000";

function authHeaders(token) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem("zen_token"));
  const [user, setUser] = useState(() => {
    const stored = localStorage.getItem("zen_user");
    return stored ? JSON.parse(stored) : null;
  });
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [memories, setMemories] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Verify token on mount and fetch nudge
  useEffect(() => {
    if (token) {
      fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
        .then((res) => { if (!res.ok) throw new Error(); return res.json(); })
        .then((data) => {
          setUser(data.user);
          // Fetch proactive nudge after auth verified
          return fetch(`${API}/nudge`, { headers: authHeaders(token) });
        })
        .then((res) => res.ok ? res.json() : null)
        .then((data) => {
          if (data?.nudge) {
            setMessages([{
              role: "assistant",
              content: data.nudge,
              isNudge: true,
              nudgeId: data.nudge_id,
            }]);
          }
        })
        .catch(() => handleLogout());
    }
  }, []);

  const handleAuth = (newToken, newUser) => {
    setToken(newToken);
    setUser(newUser);
  };

  const handleLogout = () => {
    localStorage.removeItem("zen_token");
    localStorage.removeItem("zen_user");
    setToken(null);
    setUser(null);
    setMessages([]);
    setMemories([]);
  };

  const fetchMemories = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${API}/memories`, { headers: authHeaders(token) });
      if (res.status === 401) { handleLogout(); return; }
      const data = await res.json();
      setMemories(data.memories || []);
    } catch (e) {
      console.error("Failed to fetch memories:", e);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || loading || !token) return;
    const userMsg = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    // Auto-dismiss nudge when user replies
    const nudgeMsg = messages.find((m) => m.isNudge);
    if (nudgeMsg?.nudgeId) {
      dismissNudge(nudgeMsg.nudgeId);
    }

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: authHeaders(token),
        body: JSON.stringify({ message: input }),
      });
      if (res.status === 401) { handleLogout(); return; }
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          memoriesUsed: data.memories_used,
          memoryScore: data.memory_score,
          memoryStored: data.memory_stored,
          toolsUsed: data.tools_used || [],
        },
      ]);
      fetchMemories();
    } catch (e) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: "Something went wrong. Is the backend running?" },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const deleteMemory = async (memoryId) => {
    if (!token) return;
    try {
      await fetch(`${API}/memories/${memoryId}`, { method: "DELETE", headers: authHeaders(token) });
      fetchMemories();
    } catch (e) {
      console.error("Failed to delete memory:", e);
    }
  };

  const dismissNudge = async (nudgeId) => {
    if (!token || !nudgeId) return;
    try {
      await fetch(`${API}/nudge/${nudgeId}/dismiss`, {
        method: "POST",
        headers: authHeaders(token),
      });
      setMessages((prev) => prev.filter((m) => !m.isNudge));
    } catch (e) {
      console.error("Failed to dismiss nudge:", e);
    }
  };

  const clearMemories = async () => {
    if (!token) return;
    try {
      await fetch(`${API}/memories`, { method: "DELETE", headers: authHeaders(token) });
      setMemories([]);
    } catch (e) {
      console.error("Failed to clear memories:", e);
    }
  };

  useEffect(() => {
    if (token) fetchMemories();
  }, [token]);

  if (!token) {
    return <AuthPage onAuth={handleAuth} />;
  }

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        memories={memories}
        onDeleteMemory={deleteMemory}
        onClearMemories={clearMemories}
        onRefresh={fetchMemories}
        user={user}
        onLogout={handleLogout}
      />
      <ChatView
        messages={messages}
        input={input}
        loading={loading}
        onInputChange={setInput}
        onSend={sendMessage}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        onDismissNudge={dismissNudge}
        user={user}
      />
    </div>
  );
}
