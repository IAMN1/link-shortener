/**
 * journals.js – The journal viewer page.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
//
// Two files for one page, the same split `charts.js` and
// `pages/service_stats.js` use, and for the same reason: everything that
// owns a timer lives in the file loaded once per tab, and what runs on
// every navigation is the mounting. Merged into one file loaded from the
// head, the page would never mount on a Turbo navigation; merged into one
// loaded here, every navigation would leave another timer polling.
(function () {
    mountJournals(document.querySelector('[data-journal-view]'));
})();
