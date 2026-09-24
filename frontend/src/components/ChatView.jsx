import { useRef, useEffect } from "react";
import { Send, Brain, Menu, Sparkles } from "lucide-react";

export default function ChatView({ messages, input, loading, onInputChange, onSend, onToggleSidebar }) {
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      onSend();
    }
  };

  return (
    <div className="chat-view">
      <header className="chat-header">
        <button className="icon-btn" onClick={onToggleSidebar} aria-label="Toggle sidebar">
          <Menu size={20} />
        </button>
        <div className="header-title">
          <Sparkles size={18} />
          <span>Zen Agent</span>
        </div>
        <div className="header-badge">Gemini + mem0</div>
      </header>

      <div className="messages">
        {messages.length === 0 && (
          <div className="empty-state">
            <div className="empty-icon">
              <Brain size={48} strokeWidth={1} />
            </div>
            <h2>Hello, I'm Zen</h2>
            <p>A self-learning AI agent. I remember our conversations and get better over time.</p>
            <div className="suggestions">
              {["What can you remember?", "Tell me about yourself", "How does your memory work?"].map((s) => (
                <button key={s} className="suggestion" onClick={() => { onInputChange(s); }}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.role}`}>
            <div className="message-bubble">
              {msg.role === "assistant" && msg.memoriesUsed > 0 && (
                <div className="memory-badge">
                  <Brain size={12} />
                  <span>{msg.memoriesUsed} {msg.memoriesUsed === 1 ? "memory" : "memories"} used</span>
                </div>
              )}
              <div className="message-text">{msg.content}</div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="message assistant">
            <div className="message-bubble">
              <div className="typing">
                <span></span><span></span><span></span>
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="input-area">
        <div className="input-wrapper">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message Zen..."
            rows={1}
          />
          <button
            className="send-btn"
            onClick={onSend}
            disabled={!input.trim() || loading}
            aria-label="Send message"
          >
            <Send size={18} />
          </button>
        </div>
        <p className="input-hint">Zen learns from every conversation via mem0 memory</p>
      </div>
    </div>
  );
}
