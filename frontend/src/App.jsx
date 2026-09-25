import { useState, useEffect } from "react";
import ChatView from "./components/ChatView";
import Sidebar from "./components/Sidebar";
import "./App.css";

const API = "http://localhost:8000";

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [memories, setMemories] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userId] = useState("default_user");

  const fetchMemories = async () => {
    try {
      const res = await fetch(`${API}/memories/${userId}`);
      const data = await res.json();
      setMemories(data.memories || []);
    } catch (e) {
      console.error("Failed to fetch memories:", e);
    }
  };

  const sendMessage = async () => {
    if (!input.trim() || loading) return;
    const userMsg = { role: "user", content: input };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: input, user_id: userId }),
      });
      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.response,
          memoriesUsed: data.memories_used,
          memoryScore: data.memory_score,
          memoryStored: data.memory_stored,
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
    try {
      await fetch(`${API}/memories/${userId}/${memoryId}`, { method: "DELETE" });
      fetchMemories();
    } catch (e) {
      console.error("Failed to delete memory:", e);
    }
  };

  const clearMemories = async () => {
    try {
      await fetch(`${API}/memories/${userId}`, { method: "DELETE" });
      setMemories([]);
    } catch (e) {
      console.error("Failed to clear memories:", e);
    }
  };

  useEffect(() => {
    fetchMemories();
  }, []);

  return (
    <div className="app">
      <Sidebar
        open={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        memories={memories}
        onDeleteMemory={deleteMemory}
        onClearMemories={clearMemories}
        onRefresh={fetchMemories}
      />
      <ChatView
        messages={messages}
        input={input}
        loading={loading}
        onInputChange={setInput}
        onSend={sendMessage}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
      />
    </div>
  );
}
