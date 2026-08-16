/**
 * my_stats.js – Personal statistics page.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    try {
        var resp = await apiFetch('/api/v1/stats/mine');
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('stats-error', await apiErrorText(resp), 'recent-tbody', 4);
            return;
        }
        var data = await resp.json();
        document.getElementById('stat-total-links').textContent = data.total_links;
        document.getElementById('stat-total-clicks').textContent = data.total_clicks;
        document.getElementById('stat-avg').textContent = data.avg_clicks_per_link;
        var tbody = document.getElementById('recent-tbody');
        if (data.recent_links && data.recent_links.length) {
            tbody.innerHTML = data.recent_links.map(function(l) {
                return '<tr><td class="table-mono"><a href="' + escapeHtml(l.short_url) + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(l.short_code) + '</a></td>'
                    + '<td class="cell-fill"><span class="truncate">' + escapeHtml(l.original_url) + '</span></td>'
                    + '<td>' + l.clicks + '</td>'
                    + '<td>' + formatDate(l.created_at) + '</td></tr>';
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-center">'
                + escapeHtml(t('no_links_yet')) + '</td></tr>';
        }
    } catch(e) {
        showLoadError('stats-error', t('unreachable'), 'recent-tbody', 4);
    }
})();
