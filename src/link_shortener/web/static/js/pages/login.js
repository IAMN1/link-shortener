/**
 * login.js – Login form handler.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var form = document.getElementById('login-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var email = document.getElementById('email').value;
        var password = document.getElementById('password').value;
        var errEl = document.getElementById('login-error');
        errEl.classList.add('hidden');
        try {
            var resp = await fetch('/api/v1/auth/login', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({ email: email, password: password })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('login_failed'));
            // The session arrives as HttpOnly cookies; nothing to store here.
            window.location.href = '/dashboard/';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });

    // Asks for a fresh confirmation message for whatever address is in
    // the email field. The service answers the same whether or not that
    // address is registered, so this reveals nothing the form did not.
    var resend = document.getElementById('resend-link');
    if (resend) {
        resend.addEventListener('click', async function(e) {
            e.preventDefault();
            var email = document.getElementById('email').value;
            var errEl = document.getElementById('resend-error');
            var doneEl = document.getElementById('resend-done');
            errEl.classList.add('hidden');
            doneEl.classList.add('hidden');
            if (!email) {
                errEl.textContent = t('type_address_first');
                errEl.classList.remove('hidden');
                return;
            }
            try {
                var resp = await fetch('/api/v1/auth/resend-verification', {
                    method: 'POST',
                    headers: csrfHeaders(null, 'POST'),
                    credentials: 'same-origin',
                    body: JSON.stringify({ email: email })
                });
                var data = await resp.json();
                if (!resp.ok) throw new Error(data.message || data.error || t('could_not_send'));
                // Out of the catalogue, not `data.message`: the 202 body
                // is a literal the API never translates, so this line put
                // English on a Russian page. The refusal above is the
                // other case -- that one the API does translate.
                doneEl.textContent = t('confirmation_link_sent');
                doneEl.classList.remove('hidden');
            } catch(err) {
                errEl.textContent = err.message;
                errEl.classList.remove('hidden');
            }
        });
    }
})();
