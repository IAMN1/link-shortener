/**
 * verify.js – Spends the confirmation token, on a click rather than on a
 * page load, so a mail scanner following the link cannot spend it first.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var card = document.getElementById('verify-card');
    var btn = document.getElementById('verify-btn');
    if (!card || !btn) return;
    var token = card.dataset.token;

    btn.addEventListener('click', async function() {
        var errEl = document.getElementById('verify-error');
        errEl.classList.add('hidden');
        btn.disabled = true;
        // The caption is taken from the button rather than from a string
        // here, the way `home.js` takes it. The template's word and the
        // one the failure branch below handed back agree today, and they
        // agreed in `home.js` too until a rewrite renamed one of them --
        // that is how "Look up" turned into "Get Info" on the first press.
        // Read from the button, a rename in the markup cannot be undone.
        if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
        btn.textContent = t('confirming');
        try {
            var resp = await fetch('/api/v1/auth/verify', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({ token: token })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('confirmation_failed'));
            document.getElementById('verify-done').textContent = data.message;
            document.getElementById('verify-done').classList.remove('hidden');
            document.getElementById('verify-next').classList.remove('hidden');
            btn.classList.add('hidden');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = btn.dataset.label;
        }
    });
})();
