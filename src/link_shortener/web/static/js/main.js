/**
 * Копирует текст в буфер обмена.
 * @param {string} text - Текст для копирования.
 * @returns {Promise<boolean>} - true, если успешно.
 */
export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (err) {
        console.error('Failed to copy:', err);
        return false;
    }
}

/**
 * Показывает простое уведомление (временное решение).
 * В реальном проекте заменить на красивый тост.
 * @param {string} message - Текст уведомления.
 * @param {string} type - Тип ('success', 'error', 'info').
 */
export function showNotification(message, type = 'info') {
    alert(message); // Заглушка
}