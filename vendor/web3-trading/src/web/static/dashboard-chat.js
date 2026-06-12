/**
 * Dashboard embedded chat drawer — lightweight Kia assistant.
 * Communicates with /api/chat/local_query via SSE streaming.
 */
(function () {
    const $ = (id) => document.getElementById(id);

    const els = {
        toggleBtn: $("chatToggleBtn"),
        drawer: $("chatDrawer"),
        overlay: $("chatOverlay"),
        closeBtn: $("chatDrawerClose"),
        messages: $("chatMessages"),
        input: $("chatInput"),
        sendBtn: $("chatSendBtn"),
        badge: $("chatBadge"),
    };

    const modeButtons = document.querySelectorAll(".chat-mode-btn");

    let isOpen = false;
    let isGenerating = false;
    let abortCtrl = null;
    let sessionId = generateUUID();
    let agentType = "QUICK_REASONING";
    /** 传给 /api/chat/local_query 的 Redis 拉取偏移；每个 QA 对应新队列，必须每轮从 0 开始（勿与 SSE 内事件计数混淆） */
    let redisOffset = 0;
    let currentBubble = null;
    let currentThinkingEl = null;
    let accumulatedContent = "";
    let accumulatedThinking = "";
    /** 与主站 index.html 一致：START 设置当前阶段，CONTENT+PENDING 的正文归属该阶段（非 ANSWER_RESPONSE+STREAMING） */
    let currentEventType = null;

    function generateUUID() {
        return "xxxxxxxxxxxx4xxxyxxxxxxxxxxxxxxx".replace(/[xy]/g, (c) => {
            const r = (Math.random() * 16) | 0;
            return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
        });
    }

    function escapeHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function renderMarkdown(raw) {
        if (typeof marked !== "undefined" && marked.parse) {
            try {
                return marked.parse(raw, { breaks: true, gfm: true });
            } catch (_) { /* fall through */ }
        }
        return escapeHtml(raw).replace(/\n/g, "<br>");
    }

    // --- drawer open / close ---
    function openDrawer() {
        isOpen = true;
        els.drawer.classList.add("open");
        els.overlay.classList.add("active");
        els.badge.style.display = "none";
        els.input.focus();
        if (els.messages.childElementCount === 0) showWelcome();
    }

    function closeDrawer() {
        isOpen = false;
        els.drawer.classList.remove("open");
        els.overlay.classList.remove("active");
    }

    els.toggleBtn.addEventListener("click", () => (isOpen ? closeDrawer() : openDrawer()));
    els.closeBtn.addEventListener("click", closeDrawer);
    els.overlay.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && isOpen) closeDrawer(); });

    // --- mode select ---
    modeButtons.forEach((btn) => {
        btn.addEventListener("click", () => {
            modeButtons.forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            agentType = btn.dataset.mode;
        });
    });

    // --- welcome ---
    function showWelcome() {
        const suggestions = [
            "BTC 现在适合买入吗？帮我分析一下",
            "帮我对比 SOL 和 ETH 的投资价值",
            "当前市场有哪些高机会标的？",
            "帮我制定一个 BTC 的交易计划",
        ];
        let html = `<div class="chat-welcome">
            <div class="chat-welcome-icon">🤖</div>
            <div class="chat-welcome-title">Kia 投顾助手</div>
            <div class="chat-welcome-desc">随时提问关于行情分析、交易策略、币种对比等问题</div>
            <div class="chat-welcome-suggestions">`;
        suggestions.forEach((s) => {
            html += `<button class="chat-suggestion-btn">${escapeHtml(s)}</button>`;
        });
        html += `</div></div>`;
        els.messages.innerHTML = html;

        els.messages.querySelectorAll(".chat-suggestion-btn").forEach((btn) => {
            btn.addEventListener("click", () => {
                els.input.value = btn.textContent;
                sendMessage();
            });
        });
    }

    // --- scroll ---
    function scrollToBottom() {
        requestAnimationFrame(() => {
            els.messages.scrollTop = els.messages.scrollHeight;
        });
    }

    // --- add message bubble ---
    function addUserMessage(text) {
        const welcome = els.messages.querySelector(".chat-welcome");
        if (welcome) welcome.remove();

        const div = document.createElement("div");
        div.className = "chat-msg user";
        div.innerHTML = `<div class="chat-msg-avatar">👤</div><div class="chat-msg-bubble">${escapeHtml(text)}</div>`;
        els.messages.appendChild(div);
        scrollToBottom();
    }

    function createAssistantMessage() {
        const div = document.createElement("div");
        div.className = "chat-msg assistant";
        div.innerHTML = `<div class="chat-msg-avatar">🤖</div><div class="chat-msg-bubble"><div class="chat-typing-indicator"><span></span><span></span><span></span></div></div>`;
        els.messages.appendChild(div);
        currentBubble = div.querySelector(".chat-msg-bubble");
        currentThinkingEl = null;
        accumulatedContent = "";
        accumulatedThinking = "";
        currentEventType = null;
        scrollToBottom();
    }

    function updateAssistantContent() {
        if (!currentBubble) return;
        let html = "";
        if (accumulatedThinking) {
            html += `<details class="chat-msg-thinking" open><summary>思考过程</summary><div>${renderMarkdown(accumulatedThinking)}</div></details>`;
        }
        if (accumulatedContent) {
            html += renderMarkdown(accumulatedContent);
        } else if (!accumulatedThinking) {
            html += `<div class="chat-typing-indicator"><span></span><span></span><span></span></div>`;
        }
        currentBubble.innerHTML = html;
        scrollToBottom();
    }

    function finalizeAssistant() {
        if (!currentBubble) return;
        const indicator = currentBubble.querySelector(".chat-typing-indicator");
        if (indicator) indicator.remove();
        if (accumulatedThinking) {
            const details = currentBubble.querySelector(".chat-msg-thinking");
            if (details) details.removeAttribute("open");
        }
        currentBubble = null;
        currentThinkingEl = null;
    }

    // --- send message ---
    async function sendMessage() {
        const query = els.input.value.trim();
        if (!query) return;

        if (isGenerating) {
            if (abortCtrl) abortCtrl.abort();
            finalizeAssistant();
            isGenerating = false;
            els.sendBtn.textContent = "发送";
            return;
        }

        addUserMessage(query);
        els.input.value = "";
        createAssistantMessage();

        redisOffset = 0;
        currentEventType = null;

        isGenerating = true;
        els.sendBtn.textContent = "停止";
        abortCtrl = new AbortController();

        try {
            const response = await fetch("/api/chat/local_query", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-USER-ID": "687f8003c20832000147e1d5",
                },
                body: JSON.stringify({
                    query,
                    sessionId,
                    agentType,
                    language: "zh_CN",
                    offset: redisOffset,
                }),
                signal: abortCtrl.signal,
            });

            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const contentType = response.headers.get("content-type") || "";
            if (!contentType.includes("text/event-stream")) {
                const data = await response.json();
                if (data.code === "100006" && data.msg) {
                    const parsed = typeof data.msg === "string" ? JSON.parse(data.msg) : data.msg;
                    accumulatedContent = parsed.log || JSON.stringify(data.msg);
                } else {
                    accumulatedContent = data.message || data.msg || "无法获取回复";
                }
                updateAssistantContent();
                finalizeAssistant();
                isGenerating = false;
                els.sendBtn.textContent = "发送";
                return;
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (abortCtrl.signal.aborted) break;
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.startsWith("data:")) continue;
                    const raw = line.substring(5).trim();
                    if (!raw) continue;

                    let evt;
                    try { evt = JSON.parse(raw); } catch { continue; }

                    if (evt.sessionId) sessionId = evt.sessionId;

                    const t = evt.type;
                    const s = evt.status;
                    const c = evt.content || "";

                    if (s === "START") {
                        currentEventType = t;
                        continue;
                    }
                    if (s === "END") {
                        if (
                            t === "ANSWER_RESPONSE" ||
                            t === "REPORT" ||
                            t === "QUERY_CLARIFY" ||
                            t === "DEEP_THINK" ||
                            t === "QUERY_ANALYSIS" ||
                            t === "TOOL_EXECUTION" ||
                            t === "PROGRESS" ||
                            t === "RESEARCH_DECOMPOSITION"
                        ) {
                            currentEventType = null;
                        }
                        continue;
                    }
                    if (s === "PENDING" && t === "CONTENT") {
                        if (
                            currentEventType === "ANSWER_RESPONSE" ||
                            currentEventType === "REPORT" ||
                            currentEventType === "QUERY_CLARIFY" ||
                            currentEventType === "CUSTOMER_SERVICE_RESPONSE"
                        ) {
                            accumulatedContent += c;
                            updateAssistantContent();
                        } else if (
                            currentEventType === "QUERY_ANALYSIS" ||
                            currentEventType === "TOOL_EXECUTION" ||
                            currentEventType === "DEEP_THINK" ||
                            currentEventType === "PROGRESS" ||
                            currentEventType === "RESEARCH_DECOMPOSITION"
                        ) {
                            accumulatedThinking += c;
                            updateAssistantContent();
                        }
                        continue;
                    }
                    if (t === "ANSWER_RESPONSE" || t === "REPORT") {
                        if (s === "STREAMING") {
                            accumulatedContent += c;
                            updateAssistantContent();
                        }
                    } else if (t === "QUERY_ANALYSIS" || t === "TOOL_EXECUTION" || t === "DEEP_THINK" || t === "PROGRESS" || t === "RESEARCH_DECOMPOSITION") {
                        if (s === "STREAMING") {
                            accumulatedThinking += c;
                            updateAssistantContent();
                        } else if (s === "START" && c) {
                            accumulatedThinking += c + "\n";
                            updateAssistantContent();
                        }
                    }
                }
            }
        } catch (err) {
            if (err.name !== "AbortError") {
                accumulatedContent += `\n\n⚠️ 请求失败: ${err.message}`;
                updateAssistantContent();
            }
        } finally {
            finalizeAssistant();
            isGenerating = false;
            els.sendBtn.textContent = "发送";
            abortCtrl = null;
        }
    }

    els.sendBtn.addEventListener("click", sendMessage);
    els.input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendMessage();
        }
    });
})();
