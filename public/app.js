// ====== 通用工具 ======
(function () {
    function getCsrfToken() {
        const el = document.querySelector('input[name="csrf_token"]');
        if (el && el.value) return el.value;
        const cookies = document.cookie ? document.cookie.split(';') : [];
        for (const c of cookies) {
            const [k, ...v] = c.trim().split('=');
            if (k === 'csrf_token' && v.length) return v.join('=');
        }
        return "";
    }

    async function postForm(url, data) {
        const body = new URLSearchParams(data);
        const headers = { "Content-Type": "application/x-www-form-urlencoded" };
        const csrf = getCsrfToken();
        if (csrf) headers["X-CSRF-Token"] = csrf;
        const r = await fetch(url, {
            method: "POST",
            headers: headers,
            body: body.toString(),
        });
        return r.json();
    }

    async function getJson(url) {
        const r = await fetch(url, { signal: AbortSignal.timeout(30000) });
        if (!r.ok) {
            const err = new Error(`HTTP ${r.status}`);
            err.status = r.status;
            throw err;
        }
        return r.json();
    }

    function escHtml(s) {
        const div = document.createElement("div");
        div.textContent = s == null ? "" : String(s);
        return div.innerHTML;
    }

    // ====== 登录页 ======
    const loginForm = document.getElementById("login-form");
    if (loginForm) {
        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const err = document.getElementById("err");
            err.textContent = "";
            const formData = new FormData(loginForm);
            const res = await postForm("/login", { password: formData.get("password") });
            if (res.ok) {
                window.location.href = "/dashboard";
            } else {
                err.textContent = res.error || "登录失败";
            }
        });
        return;
    }

    // ====== 控制台 ======
    let pollTimer = null;
    const LOCAL_KEY = "explib.tag-choice";
    function savedTag() { return localStorage.getItem(LOCAL_KEY) || ""; }
    function saveTag(t) { localStorage.setItem(LOCAL_KEY, t); }

    function renderPage(data) {
        // 经验列表：套用本地保存的 tag 过滤
        const tagSel = document.getElementById("filter-tag");
        if (tagSel) {
            const tag = savedTag();
            if (tag) tagSel.value = tag;
        }
        renderExperiences(data.experiences || []);
        renderPending(data.pending || []);
        renderTokens(data.tokens || []);
        // 现在 tag 过滤的初值已应用，渲染列表
        const tag = document.getElementById("filter-tag");
        if (tag) applyTagFilter();
    }

    function renderExperiences(items) {
        const wrap = document.getElementById("exp-list");
        if (!wrap) return;
        const cntEl = document.getElementById("experiences-count");
        // 不渲染原始列表，仅计数 + 触发 applyFilter
        if (cntEl) cntEl.textContent = `(${items.length})`;
        window.__ALL_EXPS__ = items;
        applyTagFilter();
    }

    function applyTagFilter() {
        const wrap = document.getElementById("exp-list");
        if (!wrap) return;
        const tagSel = document.getElementById("filter-tag");
        const tag = tagSel ? tagSel.value : "";
        saveTag(tag);
        const keywordEl = document.getElementById("search-keyword");
        const keyword = (keywordEl ? keywordEl.value : "").trim().toLowerCase();

        let list = window.__ALL_EXPS__ || [];
        if (tag) list = list.filter(e => (e.tags || "").toLowerCase().split(",").map(s => s.trim()).includes(tag));
        if (keyword) list = list.filter(e =>
            (e.title || "").toLowerCase().includes(keyword) ||
            (e.summary || "").toLowerCase().includes(keyword) ||
            (e.tags || "").toLowerCase().includes(keyword)
        );

        if (list.length === 0) {
            wrap.innerHTML = '<p class="empty">暂无经验</p>';
            return;
        }
        wrap.innerHTML = list.map(e => `
            <div class="exp-item">
                <div class="exp-head">
                    <span class="exp-title">#${escHtml(e.id)} ${escHtml(e.title)}</span>
                    ${e.project ? `<span class="exp-project">${escHtml(e.project)}</span>` : ""}
                </div>
                ${e.summary ? `<div class="exp-summary">${escHtml(e.summary)}</div>` : ""}
                <div class="exp-meta">
                    <span class="tags">${escHtml(e.tags)}</span>
                    <span class="date">${escHtml(e.updated_at || e.created_at || '')}</span>
                    <button class="del" data-id="${escHtml(e.id)}">删除</button>
                </div>
            </div>
        `).join("");

        wrap.querySelectorAll(".del").forEach(btn => {
            btn.onclick = async () => {
                const id = btn.dataset.id;
                if (!confirm(`确认删除经验 #${id}？此操作不可撤销。`)) return;
                const res = await postForm("/dashboard/delete_experience", { exp_id: id });
                if (res.ok) loadDashboard();
                else alert(res.error || "失败");
            };
        });
    }

    function renderPending(pending) {
        const wrap = document.getElementById("pending-list");
        const countEl = document.getElementById("pending-count");
        if (countEl) countEl.textContent = `(${pending.length})`;
        if (!wrap) return;
        if (pending.length === 0) {
            wrap.innerHTML = '<p class="empty">暂无待审批连接</p>';
            return;
        }
        wrap.innerHTML = pending.map(p => `
            <div class="row">
                <div class="row-main">
                    <span class="row-title">${escHtml(p.client_name)}</span>
                    <span class="row-sub">${escHtml(p.created_at || '')} · ${escHtml(p.ip || '')}</span>
                </div>
                <div class="row-actions">
                    <button class="approve" data-id="${escHtml(p.connect_id)}">同意</button>
                    <button class="deny" data-id="${escHtml(p.connect_id)}">拒绝</button>
                </div>
            </div>
        `).join("");

        wrap.querySelectorAll(".approve").forEach(btn => {
            btn.onclick = async () => {
                const res = await postForm(`/connect/${btn.dataset.id}/approve`, {});
                if (res.ok) { alert("已同意"); loadDashboard(); }
                else alert(res.error || "失败");
            };
        });
        wrap.querySelectorAll(".deny").forEach(btn => {
            btn.onclick = async () => {
                if (!confirm("确认拒绝此连接？")) return;
                const res = await postForm(`/connect/${btn.dataset.id}/deny`, {});
                if (res.ok) loadDashboard();
                else alert(res.error || "失败");
            };
        });
    }

    function renderTokens(tokens) {
        const wrap = document.getElementById("tokens-list");
        const countEl = document.getElementById("tokens-count");
        if (countEl) countEl.textContent = `(${tokens.length})`;
        if (!wrap) return;
        if (tokens.length === 0) {
            wrap.innerHTML = '<p class="empty">暂无已授权客户端</p>';
            return;
        }
        wrap.innerHTML = tokens.map(t => `
            <div class="row">
                <div class="row-main">
                    <span class="row-title">${escHtml(t.client_name)}</span>
                    <span class="row-sub">状态: ${escHtml(t.status)} · 到期 ${escHtml(t.expires_at || '')} · 最后使用 ${escHtml(t.last_used_at || '从未')}</span>
                </div>
                <div class="row-actions">
                    <button class="revoke" data-id="${t.id}">吊销</button>
                </div>
            </div>
        `).join("");

        wrap.querySelectorAll(".revoke").forEach(btn => {
            btn.onclick = async () => {
                if (!confirm("确认吊销此客户端？此操作不可撤销。")) return;
                const res = await postForm("/dashboard/delete_token", { token_id: btn.dataset.id });
                if (res.ok) loadDashboard();
                else alert(res.error || "失败");
            };
        });
    }

    async function loadDashboard(retries = 3, backoff = 1000) {
        try {
            const data = await getJson("/api/dashboard/data");
            if (!data.ok) {
                clearInterval(pollTimer);
                window.location.href = "/login";
                return;
            }
            renderPage(data);
        } catch (e) {
            console.warn("Dashboard API error:", e.status || e.message);
            if (retries > 0) {
                setTimeout(() => loadDashboard(retries - 1, backoff * 2), backoff);
            }
        }
    }

    if (window.__DATA__) {
        renderPage(window.__DATA__);
    }
    loadDashboard();
    pollTimer = setInterval(loadDashboard, 3000);

    // 搜索 & tag 筛选
    const searchBtn = document.getElementById("search-btn");
    if (searchBtn) searchBtn.onclick = applyTagFilter;
    const keywordEl = document.getElementById("search-keyword");
    if (keywordEl) keywordEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") applyTagFilter();
    });
    const tagSel = document.getElementById("filter-tag");
    if (tagSel) tagSel.onchange = applyTagFilter;

    // 退出登录
    const logoutBtn = document.getElementById("logout-btn");
    if (logoutBtn) {
        logoutBtn.onclick = async () => {
            clearInterval(pollTimer);
            await postForm("/logout", {});
            window.location.href = "/login";
        };
    }

})();
