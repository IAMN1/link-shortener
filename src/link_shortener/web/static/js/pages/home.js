/**
 * home.js – Main page: mode selector + all forms.
 */
document.addEventListener('DOMContentLoaded', function() {
    // Mode switching
    document.querySelectorAll('.mode-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            document.querySelectorAll('.mode-btn').forEach(function(b) { b.classList.remove('active'); });
            document.querySelectorAll('.mode-content').forEach(function(c) { c.classList.remove('active'); });
            btn.classList.add('active');
            var target = document.getElementById('mode-' + btn.dataset.mode);
            if (target) target.classList.add('active');
            document.getElementById('result').style.display = 'none';
        });
    });

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    // Single URL
    var formSingle = document.getElementById('form-single');
    if (formSingle) {
        formSingle.addEventListener('submit', async function(e) {
            e.preventDefault();
            var url = document.getElementById('url-single').value;
            var btn = formSingle.querySelector('button[type="submit"]');
            btn.disabled = true; btn.textContent = 'Shortening...';
            try {
                var resp = await fetch('/api/v1/shorten', {
                    method: 'POST',
                    headers: csrfHeaders(null, 'POST'),
                    credentials: 'same-origin',
                    body: JSON.stringify({ url: url })
                });
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || 'Failed');
                showResult(data);
            } catch(err) { showError(err.message); }
            btn.disabled = false; btn.textContent = 'Shorten';
        });
    }

    // Batch
    var formBatch = document.getElementById('form-batch');
    if (formBatch) {
        formBatch.addEventListener('submit', async function(e) {
            e.preventDefault();
            var raw = document.getElementById('urls-batch').value;
            var urls = raw.split('\n').map(function(u) { return u.trim(); }).filter(Boolean);
            var btn = formBatch.querySelector('button[type="submit"]');
            btn.disabled = true; btn.textContent = 'Shortening...';
            try {
                var resp = await fetch('/api/v1/batch/shorten', {
                    method: 'POST',
                    headers: csrfHeaders(null, 'POST'),
                    credentials: 'same-origin',
                    body: JSON.stringify({ urls: urls })
                });
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || 'Failed');
                var html = '<div class="result-card"><h3 style="margin-bottom:1rem;">Results</h3>';
                if (data.results) {
                    data.results.forEach(function(r) {
                        var status = r.is_new ? 'Created' : 'Existing';
                        html += '<div class="result-field"><span class="result-url">' + escapeHtml(r.short_url) + '</span>'
                            + '<button class="result-copy" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">&#128203;</button></div>'
                            + '<div class="text-xs text-muted mb-1">' + status + ' &mdash; ' + escapeHtml(r.original_url) + '</div>'
                            + deleteControl(r);
                    });
                }
                html += '</div>';
                showHtml(html);
            } catch(err) { showError(err.message); }
            btn.disabled = false; btn.textContent = 'Shorten All';
        });
    }

    // Info
    var formInfo = document.getElementById('form-info');
    if (formInfo) {
        formInfo.addEventListener('submit', async function(e) {
            e.preventDefault();
            var code = document.getElementById('code-info').value;
            var btn = formInfo.querySelector('button[type="submit"]');
            btn.disabled = true; btn.textContent = 'Loading...';
            try {
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code));
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || 'Not found');
                // clicks is null unless the viewer is entitled to the
                // link's traffic, so the stats a signed-out visitor gets
                // are the ones that say nothing about its owner.
                var stats = '<div class="stat-item"><strong>' + new Date(data.created_at).toLocaleDateString() + '</strong><span>Created</span></div>';
                // Withheld, not absent. Saying nothing made a link whose
                // traffic the viewer may not see look like a link nobody
                // has ever followed.
                var withheld = '';
                if (data.clicks !== null && data.clicks !== undefined) {
                    stats = '<div class="stat-item"><strong>' + data.clicks + '</strong><span>Clicks</span></div>'
                        + stats
                        + '<div class="stat-item"><strong>' + (data.last_accessed ? new Date(data.last_accessed).toLocaleDateString() : 'Never') + '</strong><span>Last Access</span></div>';
                } else {
                    withheld = '<p class="text-xs text-muted mt-1">'
                        + 'This link\'s traffic is shown to whoever made it.</p>';
                }
                var html = '<div class="result-card"><h3 style="margin-bottom:1rem;">Link Info</h3>'
                    + '<div class="result-field"><span class="result-url">' + escapeHtml(data.short_url) + '</span></div>'
                    + '<div class="text-sm text-muted" style="margin:0.5rem 0;">' + escapeHtml(data.original_url) + '</div>'
                    + '<div class="result-stats">' + stats + '</div>' + withheld + '</div>';
                showHtml(html);
            } catch(err) { showError(err.message); }
            btn.disabled = false; btn.textContent = 'Get Info';
        });
    }

    // Extended
    var formExtended = document.getElementById('form-extended');
    if (formExtended) {
        formExtended.addEventListener('submit', async function(e) {
            e.preventDefault();
            var code = document.getElementById('code-extended').value;
            var btn = formExtended.querySelector('button[type="submit"]');
            btn.disabled = true; btn.textContent = 'Loading...';
            try {
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code) + '/extended');
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || 'Not found');
                var html = '<div class="result-card"><h3 style="margin-bottom:1rem;">Extended Info</h3>'
                    + '<div class="result-field"><span class="result-url">' + escapeHtml(data.short_url) + '</span></div>'
                    // Classes, not literal greys. A colour written into a
                    // style attribute cannot be reached by the dark theme,
                    // and #374151 on the dark surface is 1.7:1.
                    + '<div class="text-sm text-muted" style="margin:0.5rem 0;">' + escapeHtml(data.original_url) + '</div>'
                    + '<div class="result-stats">'
                    + '<div class="stat-item"><strong>' + data.clicks + '</strong><span>Clicks</span></div>'
                    + '<div class="stat-item"><strong>' + data.age_days + '</strong><span>Days Old</span></div>'
                    + '<div class="stat-item"><strong>' + data.clicks_per_day + '</strong><span>Clicks/Day</span></div>'
                    + '</div><div class="text-xs text-muted mt-2">'
                    + (data.is_popular ? '&#9733; Popular &nbsp;' : '')
                    + (data.is_recent ? '&#9889; Recent' : '')
                    + '</div></div>';
                showHtml(html);
            } catch(err) { showError(err.message); }
            btn.disabled = false; btn.textContent = 'Get Extended Info';
        });
    }

    // A link made without an account comes back with a token that proves
    // who made it, and it is the only way its maker can ever delete it --
    // there is no account for the link to belong to. The page used to
    // drop the field on the floor, so a guest's link was undeletable
    // through the product and the endpoint that takes the token was
    // reachable only from a terminal.
    function deleteControl(data) {
        if (!data.deletion_token) return '';
        return '<div class="result-delete">'
            + '<button class="btn btn--ghost btn--sm btn--danger js-delete-made"'
            + ' data-code="' + escapeHtml(data.short_code) + '"'
            + ' data-token="' + escapeHtml(data.deletion_token) + '">Delete this link</button>'
            + '<span class="text-xs text-muted">Only from this page, and only now.</span>'
            + '</div>';
    }

    // Bound after each render, because the card is rewritten each time.
    function bindDeleteButtons() {
        document.querySelectorAll('.js-delete-made').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var code = btn.dataset.code;
                if (!confirm('Delete link ' + code + '?')) return;
                btn.disabled = true;
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code), {
                    method: 'DELETE',
                    headers: csrfHeaders({ 'X-Deletion-Token': btn.dataset.token }, 'DELETE'),
                    credentials: 'same-origin'
                });
                if (!resp.ok) {
                    showError(await apiErrorText(resp));
                    return;
                }
                btn.replaceWith(document.createTextNode('Deleted.'));
            });
        });
    }

    function showResult(data) {
        var html = '<div class="result-card">'
            + '<p class="text-xs text-muted mb-1">' + (data.is_new ? 'Created' : 'Existing') + '</p>'
            + '<div class="result-field"><span class="result-url">' + escapeHtml(data.short_url) + '</span>'
            + '<button class="result-copy" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">&#128203;</button></div>'
            + '<div class="text-sm text-muted mt-1">' + escapeHtml(data.original_url) + '</div>'
            + deleteControl(data)
            + '</div>';
        showHtml(html);
    }
    function showError(msg) {
        var r = document.getElementById('result');
        r.innerHTML = '<div class="alert alert--error">' + escapeHtml(msg) + '</div>';
        r.style.display = 'block';
    }
    function showHtml(html) {
        var r = document.getElementById('result');
        r.innerHTML = html;
        r.style.display = 'block';
        bindDeleteButtons();
    }
});
