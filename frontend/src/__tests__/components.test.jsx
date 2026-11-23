/**
 * Component rendering and interaction tests for the Zen frontend.
 *
 * These tests exercise the React components through React Testing Library,
 * covering the acceptance criteria for authentication UI, chat interface,
 * sidebar/memory management, and overall app flow.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// ---------------------------------------------------------------------------
// AuthPage component tests
// ---------------------------------------------------------------------------
describe('AuthPage', () => {
  let AuthPage

  beforeEach(async () => {
    vi.resetModules()
    const mod = await import('../components/AuthPage.jsx')
    AuthPage = mod.default
  })

  it('renders the login form by default', () => {
    render(<AuthPage onAuth={vi.fn()} />)
    expect(screen.getByText('Welcome back')).toBeTruthy()
    expect(screen.getByPlaceholderText('Email address')).toBeTruthy()
    expect(screen.getByPlaceholderText('Password')).toBeTruthy()
    expect(screen.getByText('Sign in')).toBeTruthy()
  })

  it('switches to signup form when "Sign up" is clicked', async () => {
    render(<AuthPage onAuth={vi.fn()} />)
    const switchBtn = screen.getByRole('button', { name: /sign up/i })
    await userEvent.click(switchBtn)
    expect(screen.getByText('Create your account')).toBeTruthy()
    expect(screen.getByPlaceholderText('Full name')).toBeTruthy()
  })

  it('shows error on failed login', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: 'Invalid email or password' }),
    })

    render(<AuthPage onAuth={vi.fn()} />)
    await userEvent.type(screen.getByPlaceholderText('Email address'), 'bad@example.com')
    await userEvent.type(screen.getByPlaceholderText('Password'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid email or password')).toBeTruthy()
    })
  })

  it('shows "Cannot connect to server" on network error', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'))

    render(<AuthPage onAuth={vi.fn()} />)
    await userEvent.type(screen.getByPlaceholderText('Email address'), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText('Password'), 'password')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Cannot connect to server')).toBeTruthy()
    })
  })

  it('calls onAuth with token and user on successful login', async () => {
    const onAuth = vi.fn()
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        token: 'test-token',
        user: { id: 1, name: 'Test', email: 'test@example.com' },
      }),
    })

    render(<AuthPage onAuth={onAuth} />)
    await userEvent.type(screen.getByPlaceholderText('Email address'), 'test@example.com')
    await userEvent.type(screen.getByPlaceholderText('Password'), 'password123')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(onAuth).toHaveBeenCalledWith('test-token', {
        id: 1,
        name: 'Test',
        email: 'test@example.com',
      })
    })
  })

  it('clears error when switching between login and signup', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: 'Some error' }),
    })

    render(<AuthPage onAuth={vi.fn()} />)
    await userEvent.type(screen.getByPlaceholderText('Email address'), 'a@b.com')
    await userEvent.type(screen.getByPlaceholderText('Password'), 'pass')
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Some error')).toBeTruthy()
    })

    // Switch to signup — error should clear
    await userEvent.click(screen.getByRole('button', { name: /sign up/i }))
    expect(screen.queryByText('Some error')).toBeNull()
  })
})


// ---------------------------------------------------------------------------
// ChatView component tests
// ---------------------------------------------------------------------------
describe('ChatView', () => {
  let ChatView

  beforeEach(async () => {
    vi.resetModules()
    const mod = await import('../components/ChatView.jsx')
    ChatView = mod.default
  })

  const defaultProps = {
    messages: [],
    input: '',
    loading: false,
    onInputChange: vi.fn(),
    onSend: vi.fn(),
    onToggleSidebar: vi.fn(),
    onDismissNudge: vi.fn(),
    user: { name: 'Test', email: 'test@example.com' },
  }

  it('renders empty state when no messages', () => {
    render(<ChatView {...defaultProps} />)
    expect(screen.getByText("Hello, I'm Zen")).toBeTruthy()
    expect(screen.getByText(/self-learning AI agent/)).toBeTruthy()
  })

  it('renders suggestion buttons in empty state', () => {
    render(<ChatView {...defaultProps} />)
    expect(screen.getByText('What can you remember?')).toBeTruthy()
    expect(screen.getByText('Tell me about yourself')).toBeTruthy()
  })

  it('renders user and assistant messages', () => {
    const messages = [
      { role: 'user', content: 'Hello Zen' },
      { role: 'assistant', content: 'Hi there!' },
    ]
    render(<ChatView {...defaultProps} messages={messages} />)
    expect(screen.getByText('Hello Zen')).toBeTruthy()
    expect(screen.getByText('Hi there!')).toBeTruthy()
  })

  it('renders typing indicator when loading', () => {
    render(<ChatView {...defaultProps} loading={true} />)
    const typingEl = document.querySelector('.typing')
    expect(typingEl).toBeTruthy()
  })

  it('renders memory badge on assistant message', () => {
    const messages = [{
      role: 'assistant',
      content: 'Based on your preferences...',
      memoriesUsed: 3,
      memoryScore: 4,
      memoryStored: true,
      toolsUsed: [],
    }]
    render(<ChatView {...defaultProps} messages={messages} />)
    expect(screen.getByText(/3 memories/)).toBeTruthy()
    expect(screen.getByText('4/5')).toBeTruthy()
  })

  it('renders tool badges when tools are used', () => {
    const messages = [{
      role: 'assistant',
      content: 'Search results...',
      memoriesUsed: 0,
      memoryScore: 3,
      memoryStored: false,
      toolsUsed: ['web_search'],
    }]
    render(<ChatView {...defaultProps} messages={messages} />)
    expect(screen.getByText('Web Search')).toBeTruthy()
  })

  it('renders nudge message with dismiss button', () => {
    const messages = [{
      role: 'assistant',
      content: 'How is your project going?',
      isNudge: true,
      nudgeId: 42,
    }]
    render(<ChatView {...defaultProps} messages={messages} />)
    expect(screen.getByText('Memory Nudge')).toBeTruthy()
    expect(screen.getByText('How is your project going?')).toBeTruthy()
    expect(screen.getByTitle('Dismiss')).toBeTruthy()
  })

  it('calls onDismissNudge when dismiss button is clicked', async () => {
    const onDismissNudge = vi.fn()
    const messages = [{
      role: 'assistant',
      content: 'Nudge text',
      isNudge: true,
      nudgeId: 42,
    }]
    render(<ChatView {...defaultProps} messages={messages} onDismissNudge={onDismissNudge} />)
    await userEvent.click(screen.getByTitle('Dismiss'))
    expect(onDismissNudge).toHaveBeenCalledWith(42)
  })

  it('send button is disabled when input is empty', () => {
    render(<ChatView {...defaultProps} input="" />)
    const sendBtn = screen.getByLabelText('Send message')
    expect(sendBtn.disabled).toBe(true)
  })

  it('send button is disabled when loading', () => {
    render(<ChatView {...defaultProps} input="hello" loading={true} />)
    const sendBtn = screen.getByLabelText('Send message')
    expect(sendBtn.disabled).toBe(true)
  })

  it('graph link does NOT contain token parameter', () => {
    render(<ChatView {...defaultProps} />)
    const graphLink = screen.getByText('Graph').closest('a')
    expect(graphLink.href).not.toContain('token')
    expect(graphLink.href).not.toContain('?')
  })

  it('calls onSend when send button is clicked', async () => {
    const onSend = vi.fn()
    render(<ChatView {...defaultProps} input="hello" onSend={onSend} />)
    await userEvent.click(screen.getByLabelText('Send message'))
    expect(onSend).toHaveBeenCalled()
  })

  it('calls onToggleSidebar when menu button is clicked', async () => {
    const onToggleSidebar = vi.fn()
    render(<ChatView {...defaultProps} onToggleSidebar={onToggleSidebar} />)
    await userEvent.click(screen.getByLabelText('Toggle sidebar'))
    expect(onToggleSidebar).toHaveBeenCalled()
  })
})


// ---------------------------------------------------------------------------
// Sidebar component tests
// ---------------------------------------------------------------------------
describe('Sidebar', () => {
  let Sidebar

  beforeEach(async () => {
    vi.resetModules()
    const mod = await import('../components/Sidebar.jsx')
    Sidebar = mod.default
  })

  const defaultProps = {
    open: true,
    onToggle: vi.fn(),
    memories: [],
    onDeleteMemory: vi.fn(),
    onClearMemories: vi.fn(),
    onRefresh: vi.fn(),
    user: { name: 'Alice', email: 'alice@example.com' },
    onLogout: vi.fn(),
  }

  it('renders Memory Bank title', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Memory Bank')).toBeTruthy()
  })

  it('shows empty state when no memories', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText(/No memories yet/)).toBeTruthy()
  })

  it('renders memory items', () => {
    const memories = [
      { id: 'm1', memory: 'User likes Python' },
      { id: 'm2', memory: 'User prefers dark mode' },
    ]
    render(<Sidebar {...defaultProps} memories={memories} />)
    expect(screen.getByText('User likes Python')).toBeTruthy()
    expect(screen.getByText('User prefers dark mode')).toBeTruthy()
  })

  it('shows clear all button when memories exist', () => {
    const memories = [{ id: 'm1', memory: 'test' }]
    render(<Sidebar {...defaultProps} memories={memories} />)
    expect(screen.getByText('Clear all memories')).toBeTruthy()
  })

  it('does not show clear all button when no memories', () => {
    render(<Sidebar {...defaultProps} memories={[]} />)
    expect(screen.queryByText('Clear all memories')).toBeNull()
  })

  it('displays user name and email', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('Alice')).toBeTruthy()
    expect(screen.getByText('alice@example.com')).toBeTruthy()
  })

  it('displays user avatar initial', () => {
    render(<Sidebar {...defaultProps} />)
    expect(screen.getByText('A')).toBeTruthy()
  })

  it('calls onLogout when sign out button is clicked', async () => {
    const onLogout = vi.fn()
    render(<Sidebar {...defaultProps} onLogout={onLogout} />)
    await userEvent.click(screen.getByTitle('Sign out'))
    expect(onLogout).toHaveBeenCalled()
  })

  it('calls onRefresh when refresh button is clicked', async () => {
    const onRefresh = vi.fn()
    render(<Sidebar {...defaultProps} onRefresh={onRefresh} />)
    await userEvent.click(screen.getByLabelText('Refresh memories'))
    expect(onRefresh).toHaveBeenCalled()
  })

  it('calls onToggle when close button is clicked', async () => {
    const onToggle = vi.fn()
    render(<Sidebar {...defaultProps} onToggle={onToggle} />)
    await userEvent.click(screen.getByLabelText('Close sidebar'))
    expect(onToggle).toHaveBeenCalled()
  })

  it('calls onClearMemories when clear all is clicked', async () => {
    const onClearMemories = vi.fn()
    const memories = [{ id: 'm1', memory: 'test' }]
    render(<Sidebar {...defaultProps} memories={memories} onClearMemories={onClearMemories} />)
    await userEvent.click(screen.getByText('Clear all memories'))
    expect(onClearMemories).toHaveBeenCalled()
  })

  it('has open class when open prop is true', () => {
    const { container } = render(<Sidebar {...defaultProps} open={true} />)
    expect(container.querySelector('.sidebar.open')).toBeTruthy()
  })

  it('does not have open class when open prop is false', () => {
    const { container } = render(<Sidebar {...defaultProps} open={false} />)
    expect(container.querySelector('.sidebar.open')).toBeNull()
  })
})
