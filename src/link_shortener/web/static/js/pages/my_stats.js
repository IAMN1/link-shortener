/**
 * my_stats.js – Personal statistics page.
 */
document.addEventListener('DOMContentLoaded', async function() {
    try {
        var resp = await apiFetch('/api/v1/stats/mine');
        if (!resp || !resp.ok) return;
        var data = await resp.json();
        document.getElementById('stat-total-links').textContent = data.total_links;
        document.getElementById('stat-total-clicks').textContent = data.total_clicks;
        document.getElementById('stat-avg').textContent = data.avg_clicks_per_link;
        var tbody = document.getElementById('recent-tbody');
        if (data.recent_links && data.recent_links.length) {
            tbody.innerHTML = data.recent_links.map(function(l) {
                return '<tr><td class="table-mono"><a href="' + escapeHtml(l.short_url) + '" target="_blank">' + escapeHtml(l.short_code) + '</a></td>'
                    + '<td class="truncate" style="max-width:250px">' + escapeHtml(l.original_url) + '</td>'
                    + '<td>' + l.clicks + '</td>'
                    + '<td>' + formatDate(l.created_at) + '</td></tr>';
            }).join('');
        } else {
            tbody.innerHTML = '<tr><td colspan="4" class="text-muted text-center">No links yet</td></tr>';
        }
    } catch(e) { console.error(e); }
});
