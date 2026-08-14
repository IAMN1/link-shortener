/**
 * health.js – Infrastructure health check page.
 */
document.addEventListener('DOMContentLoaded', async function() {
    try {
        var resp = await apiFetch('/api/v1/admin/health');
        if (!resp) return;
        if (!resp.ok) {
            // A health page that cannot reach the health endpoint used to
            // leave three dashes on screen, which reads as "unmeasured"
            // when the truthful answer is "the check itself failed".
            showLoadError('health-error', await apiErrorText(resp));
            render('health-db', null);
            render('health-redis', null);
            render('health-celery', null);
            return;
        }
        var data = await resp.json();
        render('health-db', data.database);
        render('health-redis', data.cache);
        render('health-celery', data.task_queue);
    } catch(e) {
        showLoadError('health-error', 'The service could not be reached.');
    }
    function render(id, ok) {
        var el = document.getElementById(id);
        if (!el) return;
        if (ok === null) {
            el.textContent = 'UNKNOWN';
            el.style.color = 'var(--c-text-2)';
            return;
        }
        el.textContent = ok ? 'OK' : 'DOWN';
        el.style.color = ok ? 'var(--c-success)' : 'var(--c-danger)';
    }
});
