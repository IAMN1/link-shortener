/**
 * my_links.js – Fetch and display user's links with delete support.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    var tbody = document.getElementById('links-tbody');
    var emptyEl = document.getElementById('links-empty');
    // Deleting is a permission of its own: an analyst reads its links and
    // may not remove them. The markup knows the answer, so it says so here
    // rather than have the button drawn and refused.
    var card = document.getElementById('links-card');
    var mayDelete = card && card.dataset.canDelete === 'yes';
    var columns = mayDelete ? 6 : 5;
    try {
        var resp = await apiFetch('/api/v1/links/mine');
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('links-error', await apiErrorText(resp), 'links-tbody', columns);
            return;
        }
        var links = await resp.json();
        if (!links.length) {
            tbody.parentElement.parentElement.classList.add('hidden');
            emptyEl.classList.remove('hidden');
            return;
        }
        tbody.innerHTML = links.map(function(l) {
            return '<tr>'
                + '<td class="table-mono"><a href="' + escapeHtml(l.short_url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(l.short_code) + '</a></td>'
                + '<td class="cell-fill"><span class="truncate">' + escapeHtml(l.original_url) + '</span></td>'
                + '<td>' + l.clicks + '</td>'
                + '<td>' + formatDate(l.created_at) + '</td>'
                + '<td>' + (l.expires_at ? formatDate(l.expires_at) : '<span class="text-muted">never</span>') + '</td>'
                + (mayDelete
                    ? '<td><button class="btn btn--ghost btn--sm del-btn" data-code="' + escapeHtml(l.short_code) + '">Delete</button></td>'
                    : '')
                + '</tr>';
        }).join('');
        tbody.querySelectorAll('.del-btn').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var code = this.dataset.code;
                if (!confirm('Delete link ' + code + '?')) return;
                var r = await apiFetch('/api/v1/links/' + encodeURIComponent(code), { method: 'DELETE' });
                if (!r) return;
                if (!r.ok) {
                    showLoadError('links-error', await apiErrorText(r));
                    return;
                }
                window.location.reload();
            });
        });
    } catch(e) {
        showLoadError('links-error', 'The service could not be reached.', 'links-tbody', columns);
    }
})();
