/**
 * users_list.js – Admin: suspend, restore and delete accounts.
 *
 * The table is rendered by the server; this file only carries out the
 * three actions the service has always offered and the page never did.
 */
document.addEventListener('DOMContentLoaded', function() {

    // One refusal is shown the same way wherever it comes from, so a
    // guard like "the last administrator may not be removed" reaches the
    // operator in the service's own words.
    async function act(row, method, path, confirmation) {
        var email = row.dataset.userEmail;
        if (confirmation && !confirm(confirmation.replace('%s', email))) return;
        var resp = await apiFetch(path, { method: method });
        if (!resp) return;
        if (!resp.ok) {
            showLoadError('users-error', await apiErrorText(resp));
            return;
        }
        window.location.reload();
    }

    document.querySelectorAll('tr[data-user-id]').forEach(function(row) {
        var id = row.dataset.userId;

        var deactivate = row.querySelector('.js-deactivate');
        if (deactivate) {
            deactivate.addEventListener('click', function() {
                act(row, 'POST', '/api/v1/admin/users/' + id + '/deactivate',
                    'Deactivate %s? They will not be able to sign in.');
            });
        }

        var activate = row.querySelector('.js-activate');
        if (activate) {
            activate.addEventListener('click', function() {
                act(row, 'POST', '/api/v1/admin/users/' + id + '/activate', null);
            });
        }

        var remove = row.querySelector('.js-delete-user');
        if (remove) {
            remove.addEventListener('click', function() {
                act(row, 'DELETE', '/api/v1/admin/users/' + id,
                    'Delete %s permanently? This cannot be undone.');
            });
        }
    });
});
