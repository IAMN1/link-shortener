import { copyToClipboard, showNotification } from './main.js';

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('shorten-form');
    const urlInput = document.getElementById('url');
    const resultDiv = document.getElementById('result');
    const submitBtn = document.getElementById('submit-btn');
    const btnText = submitBtn?.querySelector('.btn__text');
    const btnSpinner = submitBtn?.querySelector('.btn__spinner');

    if (!form) return; // если не на главной странице

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const url = urlInput.value.trim();
        if (!url) return;

        // Показываем спиннер, блокируем кнопку
        if (btnText) btnText.style.display = 'none';
        if (btnSpinner) btnSpinner.style.display = 'inline-block';
        submitBtn.disabled = true;
        resultDiv.style.display = 'none';

        try {
            const response = await fetch('/api/v1/shorten', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url }),
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.message || data.error || 'Ошибка сервера');
            }

            // Успех – рендерим результат
            renderResult(data);
            urlInput.value = ''; // очищаем поле

        } catch (error) {
            resultDiv.innerHTML = `
                <div class="error">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p class="error__message">${error.message}</p>
                </div>
            `;
            resultDiv.style.display = 'block';
        } finally {
            // Возвращаем кнопку в исходное состояние
            if (btnText) btnText.style.display = 'inline';
            if (btnSpinner) btnSpinner.style.display = 'none';
            submitBtn.disabled = false;
        }
    });

    function renderResult(data) {
        const { short_url, original_url, clicks, created_at } = data;
        const createdDate = new Date(created_at).toLocaleString();

        const html = `
            <div class="result-card">
                <h3>Ваша короткая ссылка готова!</h3>
                <div class="result-card__field">
                    <span class="result-card__url" id="short-url">${short_url}</span>
                    <button class="result-card__copy" id="copy-btn" title="Копировать">
                        <i class="fas fa-copy"></i>
                    </button>
                </div>
                <div class="result-card__stats">
                    <div class="stat-item">
                        <div class="stat-item__value">${clicks}</div>
                        <div class="stat-item__label">переходов</div>
                    </div>
                    <div class="stat-item">
                        <div class="stat-item__value">${createdDate.split(',')[0]}</div>
                        <div class="stat-item__label">создана</div>
                    </div>
                    <div class="stat-item">
                        <a href="${original_url}" target="_blank" class="btn btn--secondary btn--block">Исходный URL</a>
                    </div>
                </div>
            </div>
        `;
        resultDiv.innerHTML = html;
        resultDiv.style.display = 'block';

        // Обработчик кнопки копирования
        document.getElementById('copy-btn').addEventListener('click', async () => {
            const shortUrl = document.getElementById('short-url').textContent;
            const copied = await copyToClipboard(shortUrl);
            if (copied) {
                showNotification('Ссылка скопирована!', 'success');
            } else {
                showNotification('Не удалось скопировать', 'error');
            }
        });
    }
});