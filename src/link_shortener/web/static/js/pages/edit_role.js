/**
 * edit_role.js – Admin: edit role permissions form.
 */
document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('edit-role-form');
    if (!form) return;
    // Extract role_name from URL: /dashboard/roles/<role_name>/edit
    var parts = window.location.pathname.split('/');
    var roleName = parts[parts.length - 2];
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var permissions = Array.from(document.querySelectorAll('input[name="permissions"]:checked')).map(function(c) { return c.value; });
        var errEl = document.getElementById('edit-role-error');
        errEl.classList.add('hidden');
        try {
            var resp = await apiFetch('/api/v1/admin/roles/' + encodeURIComponent(roleName) + '/permissions', {
                method: 'PUT',
                body: JSON.stringify({ permissions: permissions })
            });
            if (!resp) return;
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.error || data.message || 'Failed');
            window.location.href = '/dashboard/roles';
        } catch(err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
        }
    });
});
