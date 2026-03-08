export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (err) {
        console.error('Failed to copy:', err);
        return false;
    }
}

export function showNotification(message, type = 'info') {
    alert(message);
}

/**
 * Экранирует специальные HTML-символы для защиты от XSS.
 * Принимает любое значение, преобразует в строку.
 * @param {*} unsafe - Данные для экранирования.
 * @returns {string} Безопасная строка с заменёнными символами.
 */
export function escapeHtml(unsafe) {
    if (unsafe === undefined || unsafe === null) {
        return '';
    }
    const str = String(unsafe);
    return str.replace(/[&<>"']/g, function(m) {
        if (m === '&') return '&amp;';
        if (m === '<') return '&lt;';
        if (m === '>') return '&gt;';
        if (m === '"') return '&quot;';
        if (m === "'") return '&#039;';
        return m;
    });
}