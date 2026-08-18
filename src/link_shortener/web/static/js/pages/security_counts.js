/**
 * security_counts.js – Mounting the security counters on the journal page.
 */
// The same split every page here uses: what owns a timer is loaded once
// per tab from the head, and this runs on every Turbo navigation.
(function () {
    mountSecurityCounts(document.querySelector('[data-security-counts]'));
})();
