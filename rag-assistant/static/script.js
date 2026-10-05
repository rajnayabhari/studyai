const chatContainer = document.getElementById('chatContainer');
const chatInput = document.getElementById('chatInput');
const sendBtn = document.getElementById('sendBtn');
const voiceBtn = document.getElementById('voiceBtn');
const ttsToggleBtn = document.getElementById('ttsToggleBtn');
const fileInput = document.getElementById('fileInput');
const attachBtn = document.getElementById('attachBtn');
const uploadStatus = document.getElementById('uploadStatus');

const summaryBtn = document.getElementById('summaryBtn');
const quizBtn = document.getElementById('quizBtn');
const flashcardBtn = document.getElementById('flashcardBtn');
const exportPdfBtn = document.getElementById('exportPdfBtn');

const toolOutput = document.getElementById('toolOutput');
const toolOutputTitle = document.getElementById('toolOutputTitle');
const toolOutputContent = document.getElementById('toolOutputContent');
const closeToolBtn = document.getElementById('closeToolBtn');

const historyList = document.getElementById('historyList');
const newChatBtn = document.getElementById('newChatBtn');

let currentSessionId = null;
let isTTSMuted = false;

// 1. Check Auth Status
async function checkAuth() {
    try {
        const res = await fetch('/auth/me');
        if (!res.ok) throw new Error('Not logged in');
        const user = await res.json();
        
        const header = document.querySelector('.sidebar-header h2');
        header.innerHTML = `Study Assistant`;
        
        const userProfile = document.getElementById('userProfile');
        userProfile.innerHTML = `
            <div style="width: 35px; height: 35px; border-radius: 50%; background: var(--accent); display: flex; align-items: center; justify-content: center; font-weight: bold; color: white; flex-shrink: 0;">
                ${user.name.charAt(0).toUpperCase()}
            </div>
            <div style="flex: 1; overflow: hidden;">
                <div style="font-weight: 500; font-size: 0.95rem; white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">${user.name}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted); white-space: nowrap; text-overflow: ellipsis; overflow: hidden;">${user.email}</div>
            </div>
            <button id="logoutBtn" style="background: rgba(255, 107, 107, 0.1); border: 1px solid rgba(255, 107, 107, 0.2); border-radius: 8px; color: #ff6b6b; cursor: pointer; padding: 8px 10px; transition: all 0.2s ease;" title="Logout" onmouseover="this.style.background='rgba(255, 107, 107, 0.2)'" onmouseout="this.style.background='rgba(255, 107, 107, 0.1)'">
                <i class="fa-solid fa-right-from-bracket"></i>
            </button>
        `;
        
        document.getElementById('logoutBtn').addEventListener('click', async (e) => {
            e.preventDefault();
            await fetch('/auth/logout', {method: 'POST'});
            window.location.reload();
        });
        
        await loadSessions();
    } catch (e) {
        document.body.innerHTML = `
            <div style="display:flex; height:100vh; width:100vw; align-items:center; justify-content:center; background:#0f172a; color:white; flex-direction:column; font-family: 'Outfit', sans-serif;">
                <h1 style="margin-bottom:20px; font-size: 2.5rem; text-align: center;" class="gradient-text">Intelligent Study Assistant</h1>
                <p style="margin-bottom: 30px; color: #94a3b8; font-size: 1.1rem;">Please log in to sync your study context</p>
                <a href="/auth/login" style="padding:15px 30px; background:var(--accent); color:white; border-radius:12px; text-decoration:none; font-weight:600; font-size: 1.1rem; box-shadow: 0 10px 25px -5px rgba(99, 102, 241, 0.4);">
                    <i class="fa-brands fa-google"></i> Login with Google
                </a>
            </div>
        `;
    }
}

checkAuth();

async function loadSessions() {
    try {
        const res = await fetch('/chat/sessions');
        const sessions = await res.json();
        
        historyList.innerHTML = '';
        sessions.forEach(sess => {
            const item = document.createElement('div');
            item.classList.add('history-item');
            if(sess.id === currentSessionId) item.classList.add('active');
            item.style.display = "flex";
            item.style.justifyContent = "space-between";
            item.style.alignItems = "center";
            item.innerHTML = `
                <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" onclick="selectSession('${sess.id}')">
                    <i class="fa-regular fa-message"></i> ${sess.title}
                </div>
                <button class="delete-chat-btn" onclick="deleteSession(event, '${sess.id}')" style="background: none; border: none; color: #ff6b6b; cursor: pointer; opacity: 0.4; transition: opacity 0.2s;" title="Delete Chat">
                    <i class="fa-solid fa-trash"></i>
                </button>
            `;
            
            item.onmouseover = () => {
                const btn = item.querySelector('.delete-chat-btn');
                if (btn) btn.style.opacity = "1";
            };
            item.onmouseout = () => {
                const btn = item.querySelector('.delete-chat-btn');
                if (btn) btn.style.opacity = "0.4";
            };
            
            historyList.appendChild(item);
        });
        
        if (sessions.length > 0 && !currentSessionId) {
            await selectSession(sessions[0].id);
        } else if (sessions.length === 0) {
            await createNewSession();
        }
    } catch (e) {
        console.error('Failed to load sessions', e);
    }
}



async function createNewSession(title = "New Conversation") {
    const res = await fetch('/chat/sessions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title})
    });
    const data = await res.json();
    currentSessionId = data.id;
    chatContainer.innerHTML = '';
    await loadSessions();
}

newChatBtn.onclick = () => createNewSession();

async function selectSession(id) {
    currentSessionId = id;
    chatContainer.innerHTML = '';
    
    Array.from(historyList.children).forEach((el, index) => {
        el.classList.remove('active');
    });
    
    // Note: Re-running loadSessions() re-renders the list so highlighting works correctly.
    // However, calling it directly here can create a double loop. 
    // We'll just manually add class for simplicity.
    const children = Array.from(historyList.children);
    // Let's just re-render
    try {
        const resList = await fetch('/chat/sessions');
        const sessions = await resList.json();
        historyList.innerHTML = '';
        sessions.forEach(sess => {
            const item = document.createElement('div');
            item.classList.add('history-item');
            if(sess.id === currentSessionId) item.classList.add('active');
            item.style.display = "flex";
            item.style.justifyContent = "space-between";
            item.style.alignItems = "center";
            item.innerHTML = `
                <div style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" onclick="selectSession('${sess.id}')">
                    <i class="fa-regular fa-message"></i> ${sess.title}
                </div>
                <button class="delete-chat-btn" onclick="deleteSession(event, '${sess.id}')" style="background: none; border: none; color: #ff6b6b; cursor: pointer; opacity: 0.4; transition: opacity 0.2s;" title="Delete Chat">
                    <i class="fa-solid fa-trash"></i>
                </button>
            `;
            
            item.onmouseover = () => {
                const btn = item.querySelector('.delete-chat-btn');
                if (btn) btn.style.opacity = "1";
            };
            item.onmouseout = () => {
                const btn = item.querySelector('.delete-chat-btn');
                if (btn) btn.style.opacity = "0.4";
            };
            
            historyList.appendChild(item);
        });
    } catch(e) {}

    const res = await fetch(`/chat/sessions/${id}/messages`);
    const messages = await res.json();
    
    messages.forEach(msg => {
        appendMessageUI(msg.role, msg.content, msg.sources);
    });
}

async function deleteSession(e, id) {
    e.stopPropagation();
    if (!confirm("Are you sure you want to delete this chat?")) return;
    
    try {
        const res = await fetch(`/chat/sessions/${id}`, { method: 'DELETE' });
        if (res.ok) {
            if (currentSessionId === id) currentSessionId = null;
            await loadSessions();
        }
    } catch (err) {
        console.error("Failed to delete session", err);
    }
}


ttsToggleBtn.addEventListener('click', () => {
    isTTSMuted = !isTTSMuted;
    if(isTTSMuted) {
        ttsToggleBtn.classList.add('muted');
        ttsToggleBtn.innerHTML = '<i class="fa-solid fa-volume-xmark"></i>';
        window.speechSynthesis.cancel();
    } else {
        ttsToggleBtn.classList.remove('muted');
        ttsToggleBtn.innerHTML = '<i class="fa-solid fa-volume-high"></i>';
    }
});

function appendMessageUI(role, content, sources = []) {
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('chat-message', role === 'user' ? 'user-message' : 'ai-message');
    
    if (role === 'user') {
        const uploadMatch = content.match(/\[System Note: I just uploaded the following documents: (.*)\. Please prioritize them for my next questions\.\]/);
        if (uploadMatch) {
            msgDiv.style.background = 'rgba(255, 255, 255, 0.03)';
            msgDiv.style.border = '1px solid var(--glass-border)';
            msgDiv.style.boxShadow = 'none';
            msgDiv.innerHTML = `<div style="display:flex; align-items:center; gap:12px;"><div style="background: rgba(99, 102, 241, 0.15); padding: 12px; border-radius: 12px;"><i class="fa-solid fa-file-pdf" style="color:var(--accent); font-size:1.5rem;"></i></div><div><div style="font-size:0.75rem; color:var(--text-muted); text-transform: uppercase; letter-spacing: 0.5px;">Attached Documents</div><div style="font-weight:500; margin-top: 3px;">${uploadMatch[1]}</div></div></div>`;
        } else {
            msgDiv.textContent = content;
        }
    } else {
        msgDiv.innerHTML = marked.parse(content);
        if (sources && sources.length > 0) {
            const expDiv = document.createElement('div');
            expDiv.classList.add('sources-expander');
            
            const header = document.createElement('div');
            header.classList.add('sources-header');
            header.innerHTML = '<span><i class="fa-solid fa-book-bookmark"></i> View Source Documents</span> <i class="fa-solid fa-chevron-down"></i>';
            
            const contentDiv = document.createElement('div');
            contentDiv.classList.add('sources-content');
            
            const ul = document.createElement('ul');
            sources.forEach(src => {
                const li = document.createElement('li');
                li.textContent = src;
                ul.appendChild(li);
            });
            contentDiv.appendChild(ul);
            
            header.onclick = () => {
                contentDiv.style.display = contentDiv.style.display === 'block' ? 'none' : 'block';
            };
            
            expDiv.appendChild(header);
            expDiv.appendChild(contentDiv);
            msgDiv.appendChild(expDiv);
        }
    }
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}

async function sendMessage(text) {
    if (!text.trim() || !currentSessionId) return;
    
    appendMessageUI('user', text);
    chatInput.value = '';
    
    const msgDiv = document.createElement('div');
    msgDiv.classList.add('chat-message', 'ai-message');
    
    const statusDiv = document.createElement('div');
    statusDiv.style.color = 'var(--accent)';
    statusDiv.style.fontSize = '0.9rem';
    statusDiv.style.marginBottom = '10px';
    statusDiv.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> Initializing Neural Pipeline...';
    
    const contentDiv = document.createElement('div');
    
    msgDiv.appendChild(statusDiv);
    msgDiv.appendChild(contentDiv);
    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    try {
        const response = await fetch('/chat/stream', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({message: text, session_id: currentSessionId})
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        
        let fullText = "";
        let sources = [];
        let isWriting = false;
        
        while(true) {
            const {value, done} = await reader.read();
            if (done) break;
            
            const chunk = decoder.decode(value, {stream: true});
            const lines = chunk.split('\n');
            
            for (let line of lines) {
                if (line.startsWith('data: ')) {
                    const dataStr = line.replace('data: ', '').trim();
                    if (dataStr === '[DONE]') {
                        statusDiv.style.display = 'none';
                        break;
                    }
                    try {
                        const data = JSON.parse(dataStr);
                        if (data.type === 'status') {
                            if (!isWriting) {
                                statusDiv.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin"></i> ${data.content}`;
                            }
                        } else if (data.type === 'token') {
                            if (!isWriting) {
                                isWriting = true;
                                statusDiv.innerHTML = `<i class="fa-solid fa-pen-nib"></i> Synthesizing response...`;
                            }
                            fullText += data.content;
                            contentDiv.innerHTML = marked.parse(fullText);
                            chatContainer.scrollTop = chatContainer.scrollHeight;
                        } else if (data.type === 'sources') {
                            sources = data.content;
                        } else if (data.type === 'error') {
                            contentDiv.innerHTML = `<span style="color: #ef4444;">Error: ${data.content}</span>`;
                            statusDiv.style.display = 'none';
                        }
                    } catch(e) {}
                }
            }
        }
        
        statusDiv.style.display = 'none';
        
        chatContainer.removeChild(msgDiv);
        appendMessageUI('assistant', fullText, sources);
        
        // Reload sessions to update title if it was first message
        loadSessions();
        
        if (!isTTSMuted) {
            const utterance = new SpeechSynthesisUtterance(fullText);
            window.speechSynthesis.speak(utterance);
        }

    } catch (e) {
        statusDiv.innerHTML = '<i class="fa-solid fa-triangle-exclamation" style="color: #ef4444;"></i> Connection error.';
    }
}

sendBtn.addEventListener('click', () => sendMessage(chatInput.value));
chatInput.addEventListener('keypress', (e) => {
    if(e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage(chatInput.value);
    }
});

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
if(SpeechRecognition) {
    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.lang = 'en-US';
    
    recognition.onstart = () => {
        voiceBtn.classList.add('recording');
        chatInput.placeholder = "Listening via local mic...";
    };
    
    recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        chatInput.value = text;
        sendMessage(text);
    };
    
    recognition.onend = () => {
        voiceBtn.classList.remove('recording');
        chatInput.placeholder = "Ask a question about your documents...";
    };
    
    voiceBtn.addEventListener('click', () => {
        recognition.start();
    });
} else {
    voiceBtn.style.display = 'none';
}

attachBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async () => {
    const files = fileInput.files;
    if(files.length === 0) return;
    
    const formData = new FormData();
    for(let f of files) formData.append('files', f);
    if (currentSessionId) {
        formData.append('session_id', currentSessionId);
    }
    
    uploadStatus.classList.remove('hidden');
    uploadStatus.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Uploading and analyzing documents...';
    uploadStatus.style.color = "var(--text-muted)";
    
    try {
        const res = await fetch('/upload', { method: 'POST', body: formData });
        if (!res.ok) {
            let errorMsg = 'Upload failed';
            try {
                const errData = await res.json();
                errorMsg = errData.message || errData.detail || 'Upload failed';
            } catch(err) {}
            throw new Error(errorMsg);
        }
        const data = await res.json();
        uploadStatus.innerHTML = "✅ " + data.message;
        uploadStatus.style.color = "var(--accent)";
        setTimeout(() => uploadStatus.classList.add('hidden'), 4000);
        
        // Render the system note in chat immediately
        const fileNames = Array.from(files).map(f => f.name).join(', ');
        appendMessageUI('user', `[System Note: I just uploaded the following documents: ${fileNames}. Please prioritize them for my next questions.]`);
    } catch(e) {
        uploadStatus.innerHTML = "❌ " + e.message;
        uploadStatus.style.color = "#ef4444";
        // Keep the error visible longer so the user can read it
        setTimeout(() => uploadStatus.classList.add('hidden'), 8000);
    }
});

function showToolOutput(title, contentMarkdown) {
    toolOutput.classList.remove('hidden');
    toolOutputTitle.textContent = title;
    toolOutputContent.innerHTML = marked.parse(contentMarkdown);
}

closeToolBtn.addEventListener('click', () => toolOutput.classList.add('hidden'));

async function runTool(endpoint, btn, icon, title, isDownload=false) {
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    btn.disabled = true;
    
    try {
        const url = currentSessionId ? `${endpoint}?session_id=${currentSessionId}` : endpoint;
        const res = await fetch(url);
        if(!res.ok) {
            let errMsg = await res.text();
            try {
                const errData = JSON.parse(errMsg);
                errMsg = errData.detail || errMsg;
            } catch(e) {}
            throw new Error(errMsg);
        }
        
        if (isDownload) {
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = endpoint.split('/').pop() + (endpoint.includes('flashcards') ? '.csv' : '.pdf');
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        } else {
            const data = await res.json();
            showToolOutput(title, data.summary || data.quiz);
        }
    } catch (e) {
        alert("Error: " + e.message);
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

summaryBtn.addEventListener('click', () => runTool('/tools/summary', summaryBtn, '', '📝 Unit Summary'));
quizBtn.addEventListener('click', () => runTool('/tools/quiz', quizBtn, '', '🧠 Practice Quiz'));
flashcardBtn.addEventListener('click', () => runTool('/tools/flashcards', flashcardBtn, '', '🃏 Flashcards', true));

exportPdfBtn.addEventListener('click', async () => {
    if(!currentSessionId) return;
    const btn = exportPdfBtn;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';
    btn.disabled = true;
    
    try {
        const res = await fetch('/tools/export_pdf', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session_id: currentSessionId})
        });
        if(!res.ok) throw new Error();
        
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'session_notes.pdf';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    } catch (e) {
        alert("Error exporting PDF.");
    } finally {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
});


