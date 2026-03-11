// Utility functions for the frontend

/**
 * Copy text to clipboard.
 * @param {string} text - Text to copy.
 * @returns {Promise<boolean>} True if successful, false otherwise.
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
 * Show a notification (simple alert for now).
 * @param {string} message - Message to display.
 * @param {string} type - 'info', 'success', 'error' (unused).
 */
export function showNotification(message, type = 'info') {
    alert(message);
}

/**
 * Escape special HTML characters to prevent XSS.
 * @param {*} unsafe - Data to escape.
 * @returns {string} Escaped string.
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
