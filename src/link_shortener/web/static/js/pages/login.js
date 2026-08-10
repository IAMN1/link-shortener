/**
 * login.js – Login form handler.
 */
document.addEventListener('DOMContentLoaded', function() {
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
            if (!resp.ok) throw new Error(data.message || data.error || 'Login failed');
            // The session arrives as HttpOnly cookies; nothing to store here.
            window.location.href = '/dashboard/';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
