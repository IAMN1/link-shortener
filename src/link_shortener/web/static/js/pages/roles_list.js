/**
 * roles_list.js – Admin: delete a role that is not a system one.
 */
document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('tr[data-role-name] .js-delete-role').forEach(function(btn) {
        btn.addEventListener('click', async function() {
            var name = btn.closest('tr').dataset.roleName;
            if (!confirm('Delete the role ' + name + '? Accounts holding it lose it.')) return;
            var resp = await apiFetch('/api/v1/admin/roles/' + encodeURIComponent(name), {
                method: 'DELETE'
            });
            if (!resp) return;
            if (!resp.ok) {
                showLoadError('roles-error', await apiErrorText(resp));
                return;
            }
            window.location.reload();
        });
    });
});
