/**
 * users_list.js – Admin: suspend, restore and delete accounts.
 *
 * The table is rendered by the server; this file only carries out the
 * three actions the service has always offered and the page never did.
 */
// Wrapped, and not waiting for `DOMContentLoaded`: every page script is
// shaped this way, and the reason is written out once beside
// `{% block scripts %}` in templates/layout/base.html.
(function() {

    // One refusal is shown the same way wherever it comes from, so a
    // guard like "the last administrator may not be removed" reaches the
    // operator in the service's own words.
    //
    // The question each control asks is written on the control, in
    // `data-confirm`, rather than passed in from here. The server draws
    // this table and knows both the sentence and the address it names, so
    // the sentence arrives translated and already filled in -- no
    // substitution happens in the browser at all. A control with no
    // `data-confirm` is one that does not ask, which is how restoring an
    // account is meant to behave.
    async function act(control, method, path) {
        var question = control.dataset.confirm;
        if (question && !confirm(question)) return;
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
                act(deactivate, 'POST', '/api/v1/admin/users/' + id + '/deactivate');
            });
        }

        var activate = row.querySelector('.js-activate');
        if (activate) {
            activate.addEventListener('click', function() {
                act(activate, 'POST', '/api/v1/admin/users/' + id + '/activate');
            });
        }

        var remove = row.querySelector('.js-delete-user');
        if (remove) {
            remove.addEventListener('click', function() {
                act(remove, 'DELETE', '/api/v1/admin/users/' + id);
            });
        }

        // Confirming by hand skips the proof that the address is readable,
        // so it asks first and says what it is skipping. The sentence that
        // says so is on the button, in `data-confirm`.
        var confirmEmail = row.querySelector('.js-confirm-email');
        if (confirmEmail) {
            confirmEmail.addEventListener('click', function() {
                act(confirmEmail, 'POST', '/api/v1/admin/users/' + id + '/verify-email');
            });
        }

        // Sending again does not change anything, so it does not ask --
        // but the page has to say it happened, since nothing on it moves.
        var resend = row.querySelector('.js-resend-verification');
        if (resend) {
            resend.addEventListener('click', async function() {
                resend.disabled = true;
                var resp = await apiFetch(
                    '/api/v1/admin/users/' + id + '/resend-verification',
                    { method: 'POST' }
                );
                if (!resp) return;
                if (!resp.ok) {
                    showLoadError('users-error', await apiErrorText(resp));
                    resend.disabled = false;
                    return;
                }
                var data = await resp.json();
                resend.replaceWith(document.createTextNode(data.message));
            });
        }
    });
})();
