import { copyToClipboard, showNotification, escapeHtml } from './main.js';

document.addEventListener('DOMContentLoaded', () => {
    const modeBtns = document.querySelectorAll('.mode-btn');
    const modeContents = {
        single: document.getElementById('mode-single'),
        batch: document.getElementById('mode-batch'),
        info: document.getElementById('mode-info'),
        extended: document.getElementById('mode-extended')
    };
    const resultDiv = document.getElementById('result');

    function setActiveMode(mode) {
        modeBtns.forEach(b => b.classList.remove('active'));
        const targetBtn = Array.from(modeBtns).find(btn => btn.dataset.mode === mode);
        if (targetBtn) targetBtn.classList.add('active');
        Object.values(modeContents).forEach(el => el.classList.remove('active'));
        if (modeContents[mode]) modeContents[mode].classList.add('active');
        resultDiv.style.display = 'none';
    }

    modeBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            setActiveMode(btn.dataset.mode);
            history.replaceState(null, '', '/');
        });
    });

    function handleUrlParams() {
        const params = new URLSearchParams(window.location.search);
        const mode = params.get('mode');
        const code = params.get('code');
        if (mode && (mode === 'info' || mode === 'extended') && code) {
            setActiveMode(mode);
            const url = mode === 'info' 
                ? `/api/v1/links/${code}`
                : `/api/v1/links/${code}/extended`;
            fetch(url)
                .then(async response => {
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.message || data.error || 'Ошибка');
                    renderResult(data, mode);
                })
                .catch(error => {
                    resultDiv.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
                    resultDiv.style.display = 'block';
                });
        }
    }
    handleUrlParams();

    function toggleLoading(btn, isLoading) {
        const textSpan = btn.querySelector('.btn__text');
        const spinnerSpan = btn.querySelector('.btn__spinner');
        if (isLoading) {
            textSpan.style.display = 'none';
            spinnerSpan.style.display = 'inline-block';
            btn.disabled = true;
        } else {
            textSpan.style.display = 'inline';
            spinnerSpan.style.display = 'none';
            btn.disabled = false;
        }
    }

    async function submitPost(url, body, mode, submitBtn) {
        resultDiv.style.display = 'none';
        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.message || data.error || 'Ошибка сервера');
            }
            renderResult(data, mode);
        } catch (error) {
            resultDiv.innerHTML = `
                <div class="error">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p class="error__message">${escapeHtml(error.message)}</p>
                </div>
            `;
            resultDiv.style.display = 'block';
        } finally {
            toggleLoading(submitBtn, false);
        }
    }

    function renderResult(data, mode) {
        if (mode === 'single') renderSingleResult(data);
        else if (mode === 'batch') renderBatchResults(data);
        else if (mode === 'info') renderInfoResult(data);
        else if (mode === 'extended') renderExtendedResult(data);
        resultDiv.style.display = 'block';
    }

    function renderSingleResult(data) {
        const { short_url, original_url, clicks, created_at } = data;
        const createdDate = new Date(created_at).toLocaleString();
        const html = `
            <div class="result-card">
                <h3>Ваша короткая ссылка готова!</h3>
                <div class="result-card__field">
                    <span class="result-card__url" id="short-url">${escapeHtml(short_url)}</span>
                    <button class="result-card__copy" id="copy-btn" title="Копировать">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
                <div class="result-card__stats">
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(clicks)}</div>
                        <div class="stat-item__label">переходов</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(createdDate.split(',')[0])}</div>
                        <div class="stat-item__label">создана</div>
                    </div>
                    <div class="stat-item">
                        <a href="${escapeHtml(original_url)}" target="_blank" class="btn btn--secondary btn--block">Исходный URL</a>
                    </div>
                </div>
            </div>
        `;
        resultDiv.innerHTML = html;
        document.getElementById('copy-btn').addEventListener('click', async () => {
            const shortUrl = document.getElementById('short-url').textContent;
            const copied = await copyToClipboard(shortUrl);
            if (copied) showNotification('Ссылка скопирована!', 'success');
            else showNotification('Не удалось скопировать', 'error');
        });
    }

    function renderBatchResults(data) {
        const { results, total, successful, failed } = data;
        let statsHtml = `
            <div style="display: flex; gap: 2rem; margin-bottom: 1rem;">
                <div><strong>Всего:</strong> ${escapeHtml(total)}</div>
                <div><strong>Успешно:</strong> ${escapeHtml(successful)}</div>
                <div><strong>Ошибок:</strong> ${escapeHtml(failed)}</div>
            </div>
        `;
        let tableHtml = `
            <table style="width:100%; border-collapse:collapse;">
                <thead>
                    <tr><th>URL</th><th>Короткая ссылка</th><th>Статус</th></tr>
                </thead>
                <tbody>
        `;
        results.forEach(item => {
            const rowStyle = item.success ? 'background:#f0fdf4;' : 'background:#fef2f2;';
            const shortUrlCell = item.success
                ? `<span>${escapeHtml(item.short_url)}</span> <button class="copy-btn" data-url="${escapeHtml(item.short_url)}" style="background:none; border:none; color:#2563eb; cursor:pointer;"><i class="fas fa-copy"></i></button>`
                : '-';
            const statusText = item.success ? '✓' : `✗ ${escapeHtml(item.error || 'Ошибка')}`;
            tableHtml += `<tr style="${escapeHtml(rowStyle)}">
                <td><a href="${escapeHtml(item.url)}" target="_blank">${escapeHtml(item.url.substring(0,50))}…</a></td>
                <td>${shortUrlCell}</td>
                <td>${escapeHtml(statusText)}</td>
            </tr>`;
        });
        tableHtml += '</tbody></table>';
        resultDiv.innerHTML = `<div class="result-card">${statsHtml}${tableHtml}</div>`;
        document.querySelectorAll('.copy-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const url = e.currentTarget.dataset.url;
                const copied = await copyToClipboard(url);
                if (copied) showNotification('Ссылка скопирована!', 'success');
                else showNotification('Не удалось скопировать', 'error');
            });
        });
    }

    function renderInfoResult(data) {
        const { short_url, original_url, clicks, created_at, last_accessed } = data;
        const createdDate = new Date(created_at).toLocaleString();
        const lastAccessed = last_accessed ? new Date(last_accessed).toLocaleString() : 'никогда';
        const html = `
            <div class="result-card">
                <h3>Информация о ссылке</h3>
                <div class="result-card__field">
                    <span class="result-card__url" id="short-url">${escapeHtml(short_url)}</span>
                    <button class="result-card__copy" id="copy-btn" title="Копировать">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
                <p><strong>Оригинальный URL:</strong> <a href="${escapeHtml(original_url)}" target="_blank">${escapeHtml(original_url)}</a></p>
                <div class="result-card__stats">
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(clicks)}</div>
                        <div class="stat-item__label">переходов</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(createdDate.split(',')[0])}</div>
                        <div class="stat-item__label">создана</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(lastAccessed.split(',')[0])}</div>
                        <div class="stat-item__label">последний доступ</div>
                    </div>
                </div>
            </div>
        `;
        resultDiv.innerHTML = html;
        document.getElementById('copy-btn').addEventListener('click', async () => {
            const shortUrl = document.getElementById('short-url').textContent;
            const copied = await copyToClipboard(shortUrl);
            if (copied) showNotification('Ссылка скопирована!', 'success');
            else showNotification('Не удалось скопировать', 'error');
        });
    }

    function renderExtendedResult(data) {
        const { short_url, original_url, clicks, created_at, last_accessed, is_popular, is_recent, age_days, clicks_per_day, last_access_days_ago } = data;
        const createdDate = new Date(created_at).toLocaleString();
        const lastAccessed = last_accessed ? new Date(last_accessed).toLocaleString() : 'никогда';
        const html = `
            <div class="result-card">
                <h3>Расширенная информация</h3>
                <div class="result-card__field">
                    <span class="result-card__url" id="short-url">${escapeHtml(short_url)}</span>
                    <button class="result-card__copy" id="copy-btn" title="Копировать">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
                <p><strong>Оригинальный URL:</strong> <a href="${escapeHtml(original_url)}" target="_blank">${escapeHtml(original_url)}</a></p>
                <div class="result-card__stats" style="grid-template-columns: repeat(4, 1fr);">
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(clicks)}</div>
                        <div class="stat-item__label">переходов</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(age_days)}</div>
                        <div class="stat-item__label">дней</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(clicks_per_day)}</div>
                        <div class="stat-item__label">/день</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${escapeHtml(is_popular ? 'Да' : 'Нет')}</div>
                        <div class="stat-item__label">популярная</div>
                    </div>
                </div>
                <p><strong>Создана:</strong> ${escapeHtml(createdDate)}</p>
                <p><strong>Последний доступ:</strong> ${escapeHtml(lastAccessed)} (${last_access_days_ago ? escapeHtml(last_access_days_ago) + ' дн. назад' : 'никогда'})</p>
                <p><strong>Недавняя:</strong> ${escapeHtml(is_recent ? 'Да' : 'Нет')}</p>
            </div>
        `;
        resultDiv.innerHTML = html;
        document.getElementById('copy-btn').addEventListener('click', async () => {
            const shortUrl = document.getElementById('short-url').textContent;
            const copied = await copyToClipboard(shortUrl);
            if (copied) showNotification('Ссылка скопирована!', 'success');
            else showNotification('Не удалось скопировать', 'error');
        });
    }

    document.getElementById('form-single').addEventListener('submit', (e) => {
        e.preventDefault();
        const url = document.getElementById('url-single').value.trim();
        if (!url) return;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        toggleLoading(submitBtn, true);
        submitPost('/api/v1/shorten', { url }, 'single', submitBtn);
    });

    document.getElementById('form-batch').addEventListener('submit', (e) => {
        e.preventDefault();
        const urlsText = document.getElementById('urls-batch').value.trim();
        if (!urlsText) return;
        const urls = urlsText.split('\n').map(l => l.trim()).filter(l => l !== '');
        if (urls.length === 0) return;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        toggleLoading(submitBtn, true);
        submitPost('/api/v1/batch/shorten', { urls }, 'batch', submitBtn);
    });

    document.getElementById('form-info').addEventListener('submit', (e) => {
        e.preventDefault();
        const code = document.getElementById('code-info').value.trim();
        if (!code) return;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        toggleLoading(submitBtn, true);
        resultDiv.style.display = 'none';
        fetch(`/api/v1/links/${code}`)
            .then(async response => {
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || data.error || 'Ошибка');
                renderResult(data, 'info');
            })
            .catch(error => {
                resultDiv.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
                resultDiv.style.display = 'block';
            })
            .finally(() => toggleLoading(submitBtn, false));
    });

    document.getElementById('form-extended').addEventListener('submit', (e) => {
        e.preventDefault();
        const code = document.getElementById('code-extended').value.trim();
        if (!code) return;
        const submitBtn = e.target.querySelector('button[type="submit"]');
        toggleLoading(submitBtn, true);
        resultDiv.style.display = 'none';
        fetch(`/api/v1/links/${code}/extended`)
            .then(async response => {
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || data.error || 'Ошибка');
                renderResult(data, 'extended');
            })
            .catch(error => {
                resultDiv.innerHTML = `<div class="error">${escapeHtml(error.message)}</div>`;
                resultDiv.style.display = 'block';
            })
            .finally(() => toggleLoading(submitBtn, false));
    });
});