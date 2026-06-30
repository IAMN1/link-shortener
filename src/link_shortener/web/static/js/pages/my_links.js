/**
 * my_links.js – Fetch and display user's links with delete support.
 */
document.addEventListener('DOMContentLoaded', async function() {
    var tbody = document.getElementById('links-tbody');
    var emptyEl = document.getElementById('links-empty');
    try {
        var resp = await apiFetch('/api/v1/links/mine');
        if (!resp || !resp.ok) return;
        var links = await resp.json();
        if (!links.length) {
            tbody.parentElement.parentElement.classList.add('hidden');
            emptyEl.classList.remove('hidden');
            return;
        }
        tbody.innerHTML = links.map(function(l) {
            return '<tr>'
                + '<td class="table-mono"><a href="' + escapeHtml(l.short_url) + '" target="_blank">' + escapeHtml(l.short_code) + '</a></td>'
                + '<td class="truncate" style="max-width:200px">' + escapeHtml(l.original_url) + '</td>'
                + '<td>' + l.clicks + '</td>'
                + '<td>' + formatDate(l.created_at) + '</td>'
                + '<td>' + (l.expires_at ? formatDate(l.expires_at) : '<span class="text-muted">never</span>') + '</td>'
                + '<td><button class="btn btn--ghost btn--sm del-btn" data-code="' + escapeHtml(l.short_code) + '">Delete</button></td>'
                + '</tr>';
        }).join('');
        tbody.querySelectorAll('.del-btn').forEach(function(btn) {
            btn.addEventListener('click', async function() {
                var code = this.dataset.code;
                if (!confirm('Delete link ' + code + '?')) return;
                var r = await apiFetch('/api/v1/links/' + encodeURIComponent(code), { method: 'DELETE' });
                if (r && r.ok) window.location.reload();
            });
        });
    } catch(e) { console.error(e); }
});
