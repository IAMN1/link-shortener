/**
 * register.js – Registration form handler.
 */
document.addEventListener('DOMContentLoaded', function() {
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
            if (!resp.ok) throw new Error(data.error || 'Registration failed');
            window.location.href = '/login';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
