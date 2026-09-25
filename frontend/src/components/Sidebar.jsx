import { Brain, Trash2, RefreshCw, X, LogOut } from "lucide-react";

export default function Sidebar({ open, onToggle, memories, onDeleteMemory, onClearMemories, onRefresh, user, onLogout }) {
  return (
    <>
      {open && <div className="sidebar-overlay" onClick={onToggle} />}
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <div className="sidebar-header">
          <div className="sidebar-title">
            <Brain size={18} />
            <span>Memory Bank</span>
          </div>
          <div className="sidebar-actions">
            <button className="icon-btn small" onClick={onRefresh} aria-label="Refresh memories" title="Refresh">
              <RefreshCw size={14} />
            </button>
            <button className="icon-btn small" onClick={onToggle} aria-label="Close sidebar">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="memories-list">
          {memories.length === 0 ? (
            <div className="no-memories">
              <p>No memories yet. Start chatting and I'll remember important things.</p>
            </div>
          ) : (
            memories.map((mem) => (
              <div key={mem.id} className="memory-item">
                <p>{mem.memory}</p>
                <button
                  className="delete-mem"
                  onClick={() => onDeleteMemory(mem.id)}
                  aria-label="Delete memory"
                >
                  <Trash2 size={12} />
                </button>
              </div>
            ))
          )}
        </div>

        {memories.length > 0 && (
          <div className="sidebar-footer">
            <button className="clear-btn" onClick={onClearMemories}>
              <Trash2 size={14} />
              Clear all memories
            </button>
          </div>
        )}

        <div className="sidebar-user">
          <div className="user-info">
            <div className="user-avatar">{user?.name?.[0]?.toUpperCase() || "?"}</div>
            <div className="user-details">
              <span className="user-name">{user?.name}</span>
              <span className="user-email">{user?.email}</span>
            </div>
          </div>
          <button className="icon-btn small" onClick={onLogout} title="Sign out">
            <LogOut size={16} />
          </button>
        </div>
      </aside>
    </>
  );
}
