/**
 * security.js – The account's own security settings.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {
    var form = document.getElementById('change-password-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var current = document.getElementById('current-password');
        var next = document.getElementById('new-password');
        var repeat = document.getElementById('repeat-password');
        var errEl = document.getElementById('password-error');
        var resultEl = document.getElementById('password-result');
        errEl.classList.add('hidden');
        resultEl.classList.add('hidden');

        // Caught here rather than sent: the second field is never posted,
        // so the service has nothing to compare it against. A password
        // mistyped identically twice is still the password -- what this
        // catches is the far likelier mistyping of one of the two.
        if (next.value !== repeat.value) {
            errEl.textContent = t('passwords_do_not_match');
            errEl.classList.remove('hidden');
            return;
        }

        try {
            var resp = await apiFetch('/api/v1/auth/change-password', {
                method: 'POST',
                body: JSON.stringify({
                    current_password: current.value,
                    new_password: next.value
                })
            });
            // `apiFetch` sends a 401 to the login page and answers null.
            // Here that means the session ended before the change was
            // made, not because of it.
            if (!resp) return;
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || t('failed'));

            resultEl.innerHTML = '<div class="alert alert--success">'
                + escapeHtml(t('password_changed')) + '</div>';
            resultEl.classList.remove('hidden');
            // Cleared on success only. Left filled after a refusal, the
            // fields would have to be retyped for a mistake in one of
            // them; cleared after success, they are not left holding the
            // new password for whoever walks past the screen.
            form.reset();
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
})();
