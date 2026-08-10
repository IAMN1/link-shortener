/**
 * create_user.js – Admin: create user form.
 */
document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('create-user-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var email = document.getElementById('email').value;
        var password = document.getElementById('password').value;
        var roles = Array.from(document.querySelectorAll('input[name="roles"]:checked')).map(function(c) { return c.value; });
        var errEl = document.getElementById('create-user-error');
        errEl.classList.add('hidden');
        try {
            var resp = await apiFetch('/api/v1/admin/users', {
                method: 'POST',
                body: JSON.stringify({ email: email, password: password, roles: roles.length ? roles : null })
            });
            if (!resp) return;
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || 'Failed');
            window.location.href = '/dashboard/users';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
