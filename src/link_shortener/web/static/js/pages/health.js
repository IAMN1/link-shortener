/**
 * health.js – Infrastructure health check page.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    try {
        var resp = await apiFetch('/api/v1/admin/health');
        if (!resp) return;
        if (!resp.ok) {
            // A health page that cannot reach the health endpoint used to
            // leave three dashes on screen, which reads as "unmeasured"
            // when the truthful answer is "the check itself failed".
            showLoadError('health-error', await apiErrorText(resp));
            render('db', null);
            render('redis', null);
            render('celery', null);
            return;
        }
        var data = await resp.json();
        render('db', data.database);
        render('redis', data.cache);
        render('celery', data.task_queue);
    } catch(e) {
        showLoadError('health-error', 'The service could not be reached.');
    }

    // State is written as a class rather than as a colour in a style
    // attribute. A literal colour cannot follow the theme, and it said
    // nothing to anyone reading the page without seeing it; a dot is a
    // shape, and it survives being printed in grey.
    function render(name, ok) {
        var word = document.getElementById('health-' + name);
        var dot = document.getElementById('dot-' + name);
        if (word) word.textContent = ok === null ? 'unknown' : (ok ? 'answering' : 'not answering');
        if (!dot) return;
        dot.className = 'dot' + (ok === null ? '' : (ok ? ' dot--ok' : ' dot--danger'));
    }
})();
