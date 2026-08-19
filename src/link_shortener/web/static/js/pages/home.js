/**
 * home.js – Main page: mode selector + all forms.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {

    // Which block a control belongs to. Making links and reading them are
    // different jobs and are two sections now, so everything below -- the
    // mode strip, the answer, the placeholder line -- has to stay inside the
    // section the control was in. Unscoped, looking a code up printed the
    // answer several hundred pixels above the form that asked for it, in the
    // shortening section, over whatever link had just been made there.
    function groupOf(el) { return el.closest('[data-modes]') || document; }
    function resultOf(el) { return groupOf(el).querySelector('[data-result]'); }
    function hintOf(el) { return groupOf(el).querySelector('[data-result-hint]'); }

    // Mode switching, scoped the same way.
    document.querySelectorAll('.mode-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var group = groupOf(btn);
            group.querySelectorAll('.mode-btn').forEach(function(b) {
                b.classList.remove('active');
                b.setAttribute('aria-pressed', 'false');
            });
            group.querySelectorAll('.mode-content').forEach(function(c) { c.classList.remove('active'); });
            btn.classList.add('active');
            btn.setAttribute('aria-pressed', 'true');
            var target = document.getElementById('mode-' + btn.dataset.mode);
            if (target) target.classList.add('active');
            clear(btn);
        });
    });

    // The page says where the answer will appear before there is one, so the
    // card no longer grows out of nothing. The line goes when the card
    // arrives, and comes back when the card is cleared.
    function clear(el) {
        var r = resultOf(el);
        if (r) r.classList.add('hidden');
        var hint = hintOf(el);
        if (hint) hint.classList.remove('hidden');
    }

    // The label a control carries while it waits, and the label it gets back
    // afterwards. Restoring it from a literal is how "Look up" turned into
    // "Get Info" on the first press: the word came from a design two
    // rewrites ago, and no test reads a button's caption. Taken from the
    // button itself, a rename in the markup can no longer be undone here.
    function busy(btn, word) {
        if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
        btn.disabled = true;
        btn.textContent = word;
    }
    function done(btn) {
        btn.disabled = false;
        btn.textContent = btn.dataset.label;
    }

    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    // The short URL, split at the last slash so the code can be made
    // unbreakable on its own.
    //
    // The whole promise on this page is a code short enough to read out
    // loud, and a narrow window was breaking it in half -- `o-` on one line
    // and `sLOrD` on the next -- because the field wrapped anywhere it
    // liked. The host may wrap; the code may not. Rendered as two adjacent
    // spans with nothing between them, so reading the field's text still
    // yields the address unchanged.
    function shortUrl(url) {
        var text = String(url == null ? '' : url);
        var cut = text.lastIndexOf('/');
        if (cut < 0) return '<span class="code-atom">' + escapeHtml(text) + '</span>';
        return '<span class="url-host">' + escapeHtml(text.slice(0, cut + 1)) + '</span>'
            + '<span class="code-atom">' + escapeHtml(text.slice(cut + 1)) + '</span>';
    }

    // Single URL
    var formSingle = document.getElementById('form-single');
    if (formSingle) {
        formSingle.addEventListener('submit', async function(e) {
            e.preventDefault();
            var url = document.getElementById('url-single').value;
            var btn = formSingle.querySelector('button[type="submit"]');
            busy(btn, t('working'));
            try {
                var resp = await fetch('/api/v1/shorten', {
                    method: 'POST',
                    headers: csrfHeaders(null, 'POST'),
                    credentials: 'same-origin',
                    body: JSON.stringify({ url: url })
                });
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || t('failed'));
                showResult(btn, data);
            } catch(err) { showError(btn, err.message); }
            done(btn);
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
            busy(btn, t('working'));
            try {
                var resp = await fetch('/api/v1/batch/shorten', {
                    method: 'POST',
                    headers: csrfHeaders(null, 'POST'),
                    credentials: 'same-origin',
                    body: JSON.stringify({ urls: urls })
                });
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || t('failed'));
                var html = '<div class="result-card"><div class="lab mb-1">' + escapeHtml(t('results')) + '</div>';
                if (data.results) {
                    data.results.forEach(function(r) {
                        // The address the caller sent comes back as `url`.
                        // This read `r.original_url`, which the schema has
                        // never had, so every line printed "Created —" with
                        // nothing after the dash.
                        if (r.success === false) {
                            // And a refused address used to be drawn as an
                            // ordinary row: an empty field, a Copy button
                            // over nothing, and the word "Existing" -- so
                            // the one thing the caller needed to know,
                            // which of their addresses was not taken and
                            // why, was the one thing not shown.
                            html += '<div class="text-xs text-muted">' + escapeHtml(r.url) + '</div>'
                                + '<div class="alert alert--error mb-1">'
                                + escapeHtml(r.error || t('refused')) + '</div>';
                            return;
                        }
                        var status = r.is_new ? t('status_created') : t('status_existing');
                        html += '<div class="result-field"><span class="result-url">' + shortUrl(r.short_url) + '</span>'
                            + '<button class="result-copy" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">' + escapeHtml(t('copy')) + '</button></div>'
                            + '<div class="text-xs text-muted mb-1">' + escapeHtml(status) + ' &mdash; ' + escapeHtml(r.url) + '</div>'
                            + deleteControl(r);
                    });
                }
                html += '</div>';
                showHtml(btn, html);
            } catch(err) { showError(btn, err.message); }
            done(btn);
        });
    }

    // Info
    var formInfo = document.getElementById('form-info');
    if (formInfo) {
        formInfo.addEventListener('submit', async function(e) {
            e.preventDefault();
            var code = document.getElementById('code-info').value;
            var btn = formInfo.querySelector('button[type="submit"]');
            busy(btn, t('looking'));
            try {
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code));
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || t('not_found'));
                // clicks is null unless the viewer is entitled to the link's
                // traffic, so the stats a signed-out visitor gets are the
                // ones that say nothing about its owner.
                // `formatDate` from `main.js` rather than a `Date` built
                // here: it writes the date in the language of the page,
                // and a second copy of that decision is a second place to
                // forget it.
                var stats = '<div class="stat-item"><strong>' + formatDate(data.created_at) + '</strong><span>' + escapeHtml(t('stat_created')) + '</span></div>';
                // Withheld, not absent. Saying nothing made a link whose
                // traffic the viewer may not see look like a link nobody has
                // ever followed.
                var withheld = '';
                if (data.clicks !== null && data.clicks !== undefined) {
                    stats = '<div class="stat-item"><strong>' + data.clicks + '</strong><span>' + escapeHtml(t('stat_clicks')) + '</span></div>'
                        + stats
                        + '<div class="stat-item"><strong>' + (data.last_accessed ? formatDate(data.last_accessed) : escapeHtml(t('stat_never'))) + '</strong><span>' + escapeHtml(t('stat_last_access')) + '</span></div>';
                } else {
                    withheld = '<p class="text-xs text-muted mt-1">'
                        + escapeHtml(t('traffic_withheld')) + '</p>';
                }
                var html = '<div class="result-card"><div class="lab mb-1">' + escapeHtml(t('link')) + '</div>'
                    + '<div class="result-field"><span class="result-url">' + shortUrl(data.short_url) + '</span></div>'
                    + '<div class="text-sm text-muted mt-1">' + escapeHtml(data.original_url) + '</div>'
                    + '<div class="result-stats">' + stats + '</div>' + withheld + '</div>';
                showHtml(btn, html);
            } catch(err) { showError(btn, err.message); }
            done(btn);
        });
    }

    // Extended
    var formExtended = document.getElementById('form-extended');
    if (formExtended) {
        formExtended.addEventListener('submit', async function(e) {
            e.preventDefault();
            var code = document.getElementById('code-extended').value;
            var btn = formExtended.querySelector('button[type="submit"]');
            busy(btn, t('looking'));
            try {
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code) + '/extended');
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || t('not_found'));
                var html = '<div class="result-card"><div class="lab mb-1">' + escapeHtml(t('extended')) + '</div>'
                    + '<div class="result-field"><span class="result-url">' + shortUrl(data.short_url) + '</span></div>'
                    // Classes, not literal greys. A colour written into a
                    // style attribute cannot be reached by the dark theme,
                    // and #374151 on the dark surface is 1.7:1.
                    + '<div class="text-sm text-muted mt-1">' + escapeHtml(data.original_url) + '</div>'
                    + '<div class="result-stats">'
                    + '<div class="stat-item"><strong>' + data.clicks + '</strong><span>' + escapeHtml(t('stat_clicks')) + '</span></div>'
                    + '<div class="stat-item"><strong>' + data.age_days + '</strong><span>' + escapeHtml(t('stat_days_old')) + '</span></div>'
                    + '<div class="stat-item"><strong>' + data.clicks_per_day + '</strong><span>' + escapeHtml(t('stat_clicks_per_day')) + '</span></div>'
                    + '</div><div class="text-xs text-muted mt-2">'
                    + (data.is_popular ? escapeHtml(t('popular')) + ' &nbsp;' : '')
                    + (data.is_recent ? escapeHtml(t('recent')) : '')
                    + '</div></div>';
                showHtml(btn, html);
            } catch(err) { showError(btn, err.message); }
            done(btn);
        });
    }

    // A link made without an account comes back with a token that proves who
    // made it, and it is the only way its maker can ever delete it -- there
    // is no account for the link to belong to. The page used to drop the
    // field on the floor, so a guest's link was undeletable through the
    // product and the endpoint that takes the token was reachable only from
    // a terminal.
    function deleteControl(data) {
        if (!data.deletion_token) return '';
        return '<div class="result-delete">'
            + '<button class="btn btn--ghost btn--sm btn--danger js-delete-made"'
            + ' data-code="' + escapeHtml(data.short_code) + '"'
            + ' data-token="' + escapeHtml(data.deletion_token) + '">' + escapeHtml(t('delete_this_link')) + '</button>'
            + '<span class="text-xs text-muted">' + escapeHtml(t('delete_token_note')) + '</span>'
            + '</div>';
    }

    // Bound after each render, because the card is rewritten each time.
    function bindDeleteButtons(scope) {
        scope.querySelectorAll('.js-delete-made').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var code = btn.dataset.code;
                if (!confirm(t('confirm_delete_link', { code: code }))) return;
                btn.disabled = true;
                var resp = await fetch('/api/v1/links/' + encodeURIComponent(code), {
                    method: 'DELETE',
                    headers: csrfHeaders({ 'X-Deletion-Token': btn.dataset.token }, 'DELETE'),
                    credentials: 'same-origin'
                });
                if (!resp.ok) {
                    // Beside the button, not over the card. `showError`
                    // replaces the whole result, and for a guest that card
                    // holds the only copy of the deletion token there will
                    // ever be -- "Only from this page, and only now". One
                    // refused attempt used to cost the link and the sole
                    // means of taking it back.
                    btn.disabled = false;
                    var note = btn.parentNode.querySelector('.js-delete-error');
                    if (!note) {
                        note = document.createElement('div');
                        note.className = 'form-error js-delete-error';
                        btn.parentNode.appendChild(note);
                    }
                    note.textContent = await apiErrorText(resp);
                    return;
                }
                btn.replaceWith(document.createTextNode(t('deleted')));
            });
        });
    }

    function showResult(from, data) {
        var html = '<div class="result-card">'
            + '<div class="lab mb-1">' + escapeHtml(data.is_new ? t('status_created') : t('status_existing')) + '</div>'
            + '<div class="result-field"><span class="result-url">' + shortUrl(data.short_url) + '</span>'
            + '<button class="result-copy" onclick="navigator.clipboard.writeText(this.previousElementSibling.textContent)">' + escapeHtml(t('copy')) + '</button></div>'
            + '<div class="text-sm text-muted mt-1">' + escapeHtml(data.original_url) + '</div>'
            + deleteControl(data)
            + '</div>';
        showHtml(from, html);
    }
    function showError(from, msg) {
        var r = resultOf(from);
        if (!r) return;
        r.innerHTML = '<div class="alert alert--error mt-1">' + escapeHtml(msg) + '</div>';
        reveal(from, r);
    }
    function showHtml(from, html) {
        var r = resultOf(from);
        if (!r) return;
        r.innerHTML = html;
        reveal(from, r);
        bindDeleteButtons(r);
    }
    function reveal(from, r) {
        r.classList.remove('hidden');
        var hint = hintOf(from);
        if (hint) hint.classList.add('hidden');
    }
})();
