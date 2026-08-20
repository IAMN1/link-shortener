/**
 * reset_password.js – Spends the reset token and sets the new password.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var card = document.getElementById('reset-card');
    var form = document.getElementById('reset-form');
    if (!card || !form) return;
    var token = card.dataset.token;

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var next = document.getElementById('new-password');
        var repeat = document.getElementById('repeat-password');
        var errEl = document.getElementById('reset-error');
        errEl.classList.add('hidden');

        // Caught here rather than sent: the second field never reaches the
        // service. It exists so that a password mistyped once does not
        // become the password of an account its owner is already locked
        // out of.
        if (next.value !== repeat.value) {
            errEl.textContent = t('passwords_do_not_match');
            errEl.classList.remove('hidden');
            return;
        }

        var btn = form.querySelector('button[type=submit]');
        if (btn.dataset.label === undefined) btn.dataset.label = btn.textContent;
        btn.disabled = true;
        btn.textContent = t('working');
        try {
            // `fetch` rather than `apiFetch`, for the reason the page next
            // door gives: nobody is signed in here.
            var resp = await fetch('/api/v1/auth/reset-password', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({
                    token: token,
                    new_password: next.value
                })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('failed'));
            document.getElementById('reset-done').textContent = t('password_reset_done');
            document.getElementById('reset-done').classList.remove('hidden');
            document.getElementById('reset-next').classList.remove('hidden');
            // The form goes, rather than being cleared and left standing.
            // The token is spent, so a second press could only be refused,
            // and a form that still invites one says otherwise.
            form.classList.add('hidden');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = btn.dataset.label;
        }
    });
})();
