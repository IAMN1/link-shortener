/**
 * user_stats.js – Admin: one account's traffic, and removing its links.
 *
 * This used to be a script written into the template, which is why it was
 * the one page whose addresses reached innerHTML unescaped.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    var card = document.getElementById('user-stats-card');
    if (!card) return;
    var userId = card.dataset.userId;
    // `link:delete_any` is the administrative permission of the set, and
    // the interface offered no way to use it: an admin could only delete
    // links it owned itself.
    var mayDelete = card.dataset.canDelete === 'yes';
    var columns = mayDelete ? 5 : 4;

    async function load() {
        var resp = await apiFetch('/api/v1/admin/users/' + encodeURIComponent(userId) + '/stats');
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('user-stats-error', await apiErrorText(resp), 'recent-tbody', columns);
            return;
        }
        var data = await resp.json();
        document.getElementById('stat-links').textContent = data.total_links;
        document.getElementById('stat-clicks').textContent = data.total_clicks;
        document.getElementById('stat-avg').textContent = data.avg_clicks_per_link;

        var tbody = document.getElementById('recent-tbody');
        if (!data.recent_links || !data.recent_links.length) {
            tbody.innerHTML = '<tr><td colspan="' + columns
                + '" class="text-muted text-center">' + escapeHtml(t('no_links')) + '</td></tr>';
            return;
        }
        tbody.innerHTML = data.recent_links.map(function(l) {
            return '<tr>'
                + '<td class="table-mono">' + escapeHtml(l.short_code || l.short_url) + '</td>'
                + '<td class="cell-fill"><span class="truncate">' + escapeHtml(l.original_url) + '</span></td>'
                + '<td>' + l.clicks + '</td>'
                + '<td>' + formatDate(l.created_at) + '</td>'
                + (mayDelete
                    ? '<td><button class="btn btn--ghost btn--sm btn--danger js-del" data-code="'
                        + escapeHtml(l.short_code) + '">' + escapeHtml(t('delete')) + '</button></td>'
                    : '')
                + '</tr>';
        }).join('');

        tbody.querySelectorAll('.js-del').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var code = btn.dataset.code;
                if (!confirm(t('confirm_delete_link_of_account', { code: code }))) return;
                var r = await apiFetch('/api/v1/links/' + encodeURIComponent(code), { method: 'DELETE' });
                if (!r) return;
                if (!r.ok) {
                    showLoadError('user-stats-error', await apiErrorText(r));
                    return;
                }
                load();
            });
        });
    }

    try {
        await load();
    } catch (e) {
        showLoadError('user-stats-error', t('unreachable'), 'recent-tbody', columns);
    }
})();
