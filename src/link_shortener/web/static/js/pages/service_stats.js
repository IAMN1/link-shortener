/**
 * service_stats.js – Service-wide statistics page.
 */
document.addEventListener('DOMContentLoaded', async function() {
    try {
        var resp = await apiFetch('/api/v1/stats');
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('service-error', await apiErrorText(resp), 'popular-tbody', 4);
            return;
        }
        var data = await resp.json();
        document.getElementById('stat-total-urls').textContent = data.total_urls;
        document.getElementById('stat-total-clicks').textContent = data.total_clicks;
        // Drawn only for a caller with `stats:view_full`; for anyone else
        // the page shows the totals and says why the list is absent.
        var tbody = document.getElementById('popular-tbody');
        if (!tbody) return;
        if (data.popular_links && data.popular_links.length) {
            tbody.innerHTML = data.popular_links.map(function(l) {
                return '<tr><td class="table-mono">' + escapeHtml(l.short_code) + '</td>'
                    + '<td class="truncate" style="max-width:250px">' + escapeHtml(l.original_url) + '</td>'
                    + '<td>' + l.clicks + '</td>'
                    + '<td>' + formatDate(l.created_at) + '</td></tr>';
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-center">No links have been visited yet</td></tr>';
        }
    } catch(e) {
        showLoadError('service-error', 'The service could not be reached.', 'popular-tbody', 4);
    }
});
