/* =========================================================================
   Agentic Browser Assistant – Application Logic
   ========================================================================= */

// --- State ---------------------------------------------------------------

const state = {
  sessionId: crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2),
  threadId: '',
  messages: [],
  isThinking: false,
  pendingApproval: false,
  pendingCalls: [],
  showSettings: false,
  history: [],
  apiKey: '',
  sidebarOpen: window.innerWidth >= 1024,
  initialized: false,
  error: null,
}

// --- DOM References ------------------------------------------------------

const $ = (sel) => document.querySelector(sel)
const $$ = (sel) => document.querySelectorAll(sel)

const dom = {
  sidebar: $('#sidebar'),
  sidebarOverlay: $('#sidebar-overlay'),
  sidebarToggle: $('#sidebar-toggle'),
  sidebarClose: $('#sidebar-close'),
  settingsToggle: $('#settings-toggle'),
  settingsPanel: $('#settings-panel'),
  settingsSection: $('#settings-section'),
  settingsClose: $('#settings-close'),
  apiKeyInput: $('#api-key-input'),
  saveApiKey: $('#save-api-key'),
  chatMessages: $('#chat-messages'),
  chatForm: $('#chat-form'),
  chatInput: $('#chat-input'),
  sendBtn: $('#send-btn'),
  clearChat: $('#clear-chat'),
  historyList: $('#history-list'),
  historyCount: $('#history-count'),
  approvalModal: $('#approval-modal'),
  pendingCalls: $('#pending-calls'),
  rejectBtn: $('#reject-btn'),
  confirmBtn: $('#confirm-btn'),
  errorBar: $('#error-bar'),
  errorText: $('#error-text'),
}

// --- API -----------------------------------------------------------------

async function apiPost(path, body) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API error ${res.status}: ${text}`)
  }
  return res.json()
}

async function apiGet(path) {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`API error ${res.status}`)
  return res.json()
}

// --- Render Helpers ------------------------------------------------------

function escapeHtml(str) {
  const div = document.createElement('div')
  div.textContent = str
  return div.innerHTML
}

function renderMarkdown(content) {
  if (typeof marked !== 'undefined' && marked.parse) {
    return marked.parse(content, { breaks: true, gfm: true })
  }
  return '<p>' + escapeHtml(content).replace(/\n/g, '<br>') + '</p>'
}

function createMessageElement(msg) {
  const role = msg.role || ''
  const content = msg.content || ''
  const div = document.createElement('div')
  div.className = 'message'

  if (role === 'system') {
    div.innerHTML = `
      <div class="message__row message__row--system">
        <div class="message__bubble message__bubble--system">${escapeHtml(content)}</div>
      </div>
    `
    return div
  }

  const isUser = role === 'user'
  div.innerHTML = `
    <div class="message__row ${isUser ? 'message__row--user' : 'message__row--agent'}">
      ${isUser ? '' : `<div class="message__avatar message__avatar--agent">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" />
        </svg>
      </div>`}
      <div class="message__bubble ${isUser ? 'message__bubble--user' : 'message__bubble--agent'}">
        <div class="prose">${isUser ? escapeHtml(content) : renderMarkdown(content)}</div>
      </div>
      ${isUser ? `<div class="message__avatar message__avatar--user">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2" /><circle cx="12" cy="7" r="4" />
        </svg>
      </div>` : ''}
    </div>
  `
  return div
}

function createThinkingElement() {
  const div = document.createElement('div')
  div.className = 'thinking-indicator'
  div.id = 'thinking-indicator'
  div.innerHTML = `
    <div class="thinking-indicator__row">
      <div class="message__avatar message__avatar--agent">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="11" width="18" height="10" rx="2" /><circle cx="12" cy="5" r="2" /><path d="M12 7v4" /><line x1="8" y1="16" x2="8" y2="16" /><line x1="16" y1="16" x2="16" y2="16" />
        </svg>
      </div>
      <div class="thinking-indicator__dots">
        <div class="thinking-indicator__dot"></div>
        <div class="thinking-indicator__dot"></div>
        <div class="thinking-indicator__dot"></div>
      </div>
      <div class="thinking-indicator__text">Thinking</div>
    </div>
  `
  return div
}

function createPendingCallElement(call) {
  const div = document.createElement('div')
  div.className = 'pending-call'
  div.innerHTML = `
    <div class="pending-call__header">
      <div class="pending-call__icon-wrap">
        <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
        </svg>
      </div>
      <span class="pending-call__name">${escapeHtml(call.name || '')}</span>
    </div>
    <div class="pending-call__args">${escapeHtml(JSON.stringify(call.args || {}, null, 2))}</div>
  `
  return div
}

function createHistoryItem(entry) {
  const btn = document.createElement('button')
  btn.className = 'history-item'
  btn.innerHTML = `
    <span class="history-item__label">${escapeHtml(entry.label || entry.input || '')}</span>
    <span class="history-item__time">${escapeHtml(entry.time_str || '')}</span>
  `
  btn.addEventListener('click', () => loadConversation(entry))
  return btn
}

// --- Render Functions ----------------------------------------------------

function renderMessages() {
  dom.chatMessages.innerHTML = ''
  for (const msg of state.messages) {
    dom.chatMessages.appendChild(createMessageElement(msg))
  }
  if (state.isThinking) {
    dom.chatMessages.appendChild(createThinkingElement())
  }
  scrollToBottom()
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    dom.chatMessages.scrollTop = dom.chatMessages.scrollHeight
  })
}

function renderHistory() {
  dom.historyList.innerHTML = ''
  if (state.history.length === 0) {
    dom.historyList.innerHTML = `
      <div class="sidebar__history-empty">
        <svg class="icon sidebar__history-empty-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
        </svg>
        <span>No past sessions yet.</span>
        <span class="sidebar__history-empty-sub">Your conversation history will appear here.</span>
      </div>
    `
    dom.historyCount.textContent = ''
    return
  }
  for (const entry of state.history) {
    dom.historyList.appendChild(createHistoryItem(entry))
  }
  dom.historyCount.textContent = state.history.length
}

function renderApprovalModal() {
  if (state.pendingApproval && state.pendingCalls.length > 0) {
    dom.pendingCalls.innerHTML = ''
    for (const call of state.pendingCalls) {
      dom.pendingCalls.appendChild(createPendingCallElement(call))
    }
    dom.approvalModal.classList.remove('hidden')
  } else {
    dom.approvalModal.classList.add('hidden')
  }
}

function renderSidebar() {
  if (state.sidebarOpen) {
    dom.sidebar.classList.add('open')
    dom.sidebarOverlay.classList.remove('hidden')
  } else {
    dom.sidebar.classList.remove('open')
    dom.sidebarOverlay.classList.add('hidden')
  }
}

function renderSettings() {
  if (state.showSettings) {
    dom.settingsSection.classList.add('hidden')
    dom.settingsPanel.classList.remove('hidden')
    dom.apiKeyInput.value = state.apiKey
  } else {
    dom.settingsSection.classList.remove('hidden')
    dom.settingsPanel.classList.add('hidden')
  }
}

function renderError() {
  if (state.error) {
    dom.errorText.textContent = state.error
    dom.errorBar.classList.remove('hidden')
  } else {
    dom.errorBar.classList.add('hidden')
  }
}

function renderAll() {
  renderMessages()
  renderHistory()
  renderApprovalModal()
  renderSidebar()
  renderSettings()
  renderError()
  updateSendButton()
}

// --- Actions -------------------------------------------------------------

function updateSendButton() {
  dom.sendBtn.disabled = state.isThinking || !dom.chatInput.value.trim()
}

function generateSessionId() {
  if (crypto.randomUUID) return crypto.randomUUID()
  return 'ui-' + Math.random().toString(36).slice(2, 14)
}

async function initSession() {
  state.sessionId = generateSessionId()
  try {
    const data = await apiPost('/api/init', { session_id: state.sessionId })
    state.threadId = data.thread_id
    state.messages = data.messages || []
    state.history = data.history || []
    state.apiKey = data.api_key_configured ? '···configured···' : ''
    state.initialized = true
    state.error = data.error || null
  } catch (err) {
    state.error = `Failed to initialize: ${err.message}`
  }
  renderAll()
}

async function sendMessage(text) {
  state.isThinking = true
  renderAll()

  try {
    const data = await apiPost('/api/chat/send', {
      session_id: state.sessionId,
      text,
    })
    applyChatResponse(data)
  } catch (err) {
    state.isThinking = false
    state.error = `Failed to send message: ${err.message}`
    renderAll()
  }
}

async function approveAction() {
  state.pendingApproval = false
  state.isThinking = true
  renderAll()

  try {
    const data = await apiPost('/api/chat/approve', {
      session_id: state.sessionId,
    })
    applyChatResponse(data)
  } catch (err) {
    state.isThinking = false
    state.error = `Failed to approve: ${err.message}`
    renderAll()
  }
}

async function rejectAction() {
  state.isThinking = true
  renderAll()

  try {
    const data = await apiPost('/api/chat/reject', {
      session_id: state.sessionId,
    })
    applyChatResponse(data)
  } catch (err) {
    state.isThinking = false
    state.error = `Failed to reject: ${err.message}`
    renderAll()
  }
}

async function clearChat() {
  try {
    const data = await apiPost('/api/chat/clear', {
      session_id: state.sessionId,
    })
    applyChatResponse(data)
  } catch (err) {
    state.error = `Failed to clear: ${err.message}`
    renderAll()
  }
}

async function loadConversation(entry) {
  try {
    const data = await apiPost('/api/chat/load', {
      session_id: state.sessionId,
      thread_id: entry.thread_id || entry.threadId,
      label: entry.label || entry.input || '',
    })
    applyChatResponse(data)
    if (window.innerWidth < 1024) {
      state.sidebarOpen = false
      renderSidebar()
    }
  } catch (err) {
    state.error = `Failed to load conversation: ${err.message}`
    renderAll()
  }
}

async function saveApiKey() {
  const key = dom.apiKeyInput.value.trim()
  if (!key) return
  try {
    const data = await apiPost('/api/settings/api-key', {
      session_id: state.sessionId,
      api_key: key,
    })
    applyChatResponse(data)
    state.apiKey = '···configured···'
    state.showSettings = false
    renderAll()
  } catch (err) {
    state.error = `Failed to save API key: ${err.message}`
    renderAll()
  }
}

function applyChatResponse(data) {
  state.messages = data.messages || []
  state.isThinking = data.is_thinking || false
  state.pendingApproval = data.pending_approval || false
  state.pendingCalls = data.pending_calls || []
  state.threadId = data.thread_id || state.threadId
  state.history = data.history || []
  state.error = data.error || null
  renderAll()
}

// --- Event Handlers ------------------------------------------------------

dom.chatForm.addEventListener('submit', async (e) => {
  e.preventDefault()
  const text = dom.chatInput.value.trim()
  if (!text || state.isThinking) return
  dom.chatInput.value = ''
  updateSendButton()
  await sendMessage(text)
})

dom.chatInput.addEventListener('input', updateSendButton)
dom.chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    dom.chatForm.dispatchEvent(new Event('submit'))
  }
})

dom.sidebarToggle.addEventListener('click', () => {
  state.sidebarOpen = !state.sidebarOpen
  renderSidebar()
})

dom.sidebarClose.addEventListener('click', () => {
  state.sidebarOpen = false
  renderSidebar()
})

dom.sidebarOverlay.addEventListener('click', () => {
  state.sidebarOpen = false
  renderSidebar()
})

dom.settingsToggle.addEventListener('click', () => {
  state.showSettings = true
  renderSettings()
})

dom.settingsClose.addEventListener('click', () => {
  state.showSettings = false
  renderSettings()
})

dom.saveApiKey.addEventListener('click', saveApiKey)
dom.apiKeyInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') saveApiKey()
})

dom.clearChat.addEventListener('click', clearChat)

dom.confirmBtn.addEventListener('click', approveAction)
dom.rejectBtn.addEventListener('click', rejectAction)

// --- Auto-scroll via MutationObserver ------------------------------------

const scrollObserver = new MutationObserver(() => {
  scrollToBottom()
})

function observeMessages() {
  scrollObserver.disconnect()
  scrollObserver.observe(dom.chatMessages, {
    childList: true,
    subtree: true,
    attributes: false,
  })
}

// --- Initialize ----------------------------------------------------------

async function init() {
  observeMessages()
  renderAll()
  await initSession()
}

init()
