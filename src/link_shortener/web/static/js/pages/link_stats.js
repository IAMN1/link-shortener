/**
 * link_stats.js – One link's own page.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(async function() {
    var block = document.querySelector('[data-visit-scope]');
    if (!block) return;
    var code = block.getAttribute('data-visit-code');

    // The charts first: they fetch for themselves, so a slow answer about
    // the link does not hold them back.
    mountVisitCharts(block);

    try {
        // The extended endpoint, not the basic one: it is restricted to
        // the link's owner, an admin and `stats:view_any` -- the same
        // three the charts on this page will answer for. A page that
        // filled its tiles from the public endpoint would say more about
        // a stranger's link than the charts beneath it are willing to.
        var resp = await apiFetch('/api/v1/links/' + encodeURIComponent(code) + '/extended');
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('link-error', await apiErrorText(resp));
            return;
        }
        var data = await resp.json();
        document.getElementById('link-destination').textContent = data.original_url;
        document.getElementById('link-clicks').textContent = formatNumber(data.clicks);
        document.getElementById('link-per-day').textContent = formatNumber(data.clicks_per_day);
        document.getElementById('link-created').textContent = formatDate(data.created_at);
        document.getElementById('link-last').textContent = data.last_accessed
            ? formatDate(data.last_accessed)
            : t('stat_never');
    } catch(e) {
        showLoadError('link-error', t('unreachable'));
    }
})();
