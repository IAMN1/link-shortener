/**
 * verify.js – Spends the confirmation token, on a click rather than on a
 * page load, so a mail scanner following the link cannot spend it first.
 */
document.addEventListener('DOMContentLoaded', function() {
    var card = document.getElementById('verify-card');
    var btn = document.getElementById('verify-btn');
    if (!card || !btn) return;
    var token = card.dataset.token;

    btn.addEventListener('click', async function() {
        var errEl = document.getElementById('verify-error');
        errEl.classList.add('hidden');
        btn.disabled = true;
        btn.textContent = 'Confirming...';
        try {
            var resp = await fetch('/api/v1/auth/verify', {
                method: 'POST',
                headers: csrfHeaders(null, 'POST'),
                credentials: 'same-origin',
                body: JSON.stringify({ token: token })
            });
            var data = await resp.json();
            if (!resp.ok) throw new Error(data.message || data.error || 'Confirmation failed');
            document.getElementById('verify-done').textContent = data.message;
            document.getElementById('verify-done').classList.remove('hidden');
            document.getElementById('verify-next').classList.remove('hidden');
            btn.classList.add('hidden');
        } catch (err) {
            errEl.textContent = err.message;
            errEl.classList.remove('hidden');
            btn.disabled = false;
            btn.textContent = 'Confirm this address';
        }
    });
});
