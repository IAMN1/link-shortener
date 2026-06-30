/**
 * create_role.js – Admin: create role form.
 */
document.addEventListener('DOMContentLoaded', function() {
    var form = document.getElementById('create-role-form');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        var name = document.getElementById('name').value;
        var description = document.getElementById('description').value;
        var permissions = Array.from(document.querySelectorAll('input[name="permissions"]:checked')).map(function(c) { return c.value; });
        var errEl = document.getElementById('create-role-error');
        errEl.classList.add('hidden');
        try {
            var resp = await apiFetch('/api/v1/admin/roles', {
                method: 'POST',
                body: JSON.stringify({ name: name, description: description, permissions: permissions })
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
