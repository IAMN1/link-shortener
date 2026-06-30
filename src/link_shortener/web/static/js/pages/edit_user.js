/**
 * edit_user.js – Admin: edit user roles form.
 */
document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('edit-user-form');
    if (!form) return;
    // Extract user_id from URL: /dashboard/users/<user_id>/edit
    var parts = window.location.pathname.split('/');
    var userId = parts[parts.length - 2];
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var roles = Array.from(document.querySelectorAll('input[name="roles"]:checked')).map(function(c) { return c.value; });
        var errEl = document.getElementById('edit-user-error');
        errEl.classList.add('hidden');
        try {
            var resp = await apiFetch('/api/v1/admin/users/' + userId + '/roles', {
                method: 'PUT',
                body: JSON.stringify({ roles: roles })
            });
            if (!resp) return;
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.error || data.message || 'Failed');
            window.location.href = '/dashboard/users';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
