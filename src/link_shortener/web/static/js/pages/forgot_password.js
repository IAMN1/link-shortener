/**
 * forgot_password.js – Asks for a password reset link.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var form = document.getElementById('forgot-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var errEl = document.getElementById('forgot-error');
        var doneEl = document.getElementById('forgot-done');
        errEl.classList.add('hidden');
        doneEl.classList.add('hidden');
        var btn = form.querySelector('button[type=submit]');
        if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
        btn.disabled = true;
        btn.textContent = t('working');
        try {
            // `fetch` rather than `apiFetch`: this page is opened by
            // somebody who cannot sign in, and `apiFetch` answers a 401 by
            // sending the browser to the login form.
            var resp = await fetch('/api/v1/auth/forgot-password', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({
                    email: document.getElementById('email').value
                })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('failed'));
            // The catalogue's sentence, not the service's: the answer is
            // the same for every address, so there is nothing in the body
            // worth showing, and this way it is in the reader's language.
            doneEl.textContent = t('reset_link_sent');
            doneEl.classList.remove('hidden');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        } finally {
            btn.disabled = false;
            btn.textContent = btn.dataset.label;
        }
    });
})();
