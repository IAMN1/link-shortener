/**
 * register.js – Registration form handler.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var form = document.getElementById('register-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var email = document.getElementById('email').value;
        var password = document.getElementById('password').value;
        var errEl = document.getElementById('reg-error');
        errEl.classList.add('hidden');
        try {
            var resp = await fetch('/api/v1/auth/register', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({ email: email, password: password })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('registration_failed'));
            // Not a redirect to /login any more. The account cannot sign in
            // until the mailed link is opened, and the answer is the same
            // whether or not the address was free -- so the page says what
            // the API said and lets the person go read their mail.
            //
            // Out of the catalogue rather than `data.message`, which is
            // the API's own English: the 202 body is a literal, not a
            // translated refusal, so on a Russian page it arrived in
            // English. The same sentence, in the reader's language.
            document.getElementById('reg-sent').textContent = t('registration_link_sent');
            document.getElementById('reg-sent').classList.remove('hidden');
            form.classList.add('hidden');
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
})();
