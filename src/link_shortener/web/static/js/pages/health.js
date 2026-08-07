/**
 * health.js – Infrastructure health check page.
 */
document.addEventListener('DOMContentLoaded', async function() {
    try {
        var resp = await apiFetch('/api/v1/admin/health');
        if (!resp || !resp.ok) return;
        var data = await resp.json();
        render('health-db', data.database);
        render('health-redis', data.cache);
        render('health-celery', data.task_queue);
    } catch(e) { console.error(e); }
    function render(id, ok) {
        var el = document.getElementById(id);
        el.textContent = ok ? 'OK' : 'DOWN';
        el.style.color = ok ? 'var(--c-success)' : 'var(--c-danger)';
    }
});
