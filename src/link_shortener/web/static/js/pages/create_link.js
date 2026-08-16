/**
 * create_link.js – Create link form.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var form = document.getElementById('create-link-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var url = document.getElementById('url').value;
        var ttl = parseInt(document.getElementById('ttl').value) || 0;
        var errEl = document.getElementById('create-error');
        var resultEl = document.getElementById('create-result');
        errEl.classList.add('hidden');
        resultEl.classList.add('hidden');
        try {
            var body = { url: url };
            if (ttl > 0) body.ttl_seconds = ttl;
            var resp = await apiFetch('/api/v1/shorten', {
                method: 'POST',
                body: JSON.stringify(body)
            });
            if (!resp) return;
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('failed'));
            resultEl.innerHTML = '<div class="alert alert--success">'
                + '<strong>' + escapeHtml(data.short_url) + '</strong>'
                + '<br><span class="text-sm text-muted">' + escapeHtml(data.original_url) + '</span>'
                + '</div>';
            resultEl.classList.remove('hidden');
            document.getElementById('url').value = '';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
})();
