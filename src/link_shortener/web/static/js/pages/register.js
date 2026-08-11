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
            if (!resp.ok) throw new Error(data.message || data.error || 'Registration failed');
            // Not a redirect to /login any more. The account cannot sign in
            // until the mailed link is opened, and the answer is the same
            // whether or not the address was free -- so the page says what
            // the API said and lets the person go read their mail.
            document.getElementById('reg-sent').textContent = data.message;
            document.getElementById('reg-sent').classList.remove('hidden');
            form.classList.add('hidden');
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
