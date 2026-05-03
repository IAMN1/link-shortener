// admin.js

const TOKEN_KEY = 'admin_token';

function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}
function setToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
}
function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
}
function isAuthenticated() {
    return !!getToken();
}

async function logout() {
    clearToken();
    await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'same-origin' });
    window.location.href = '/admin/login';
}

// Обновление токена
let isRefreshing = false;
let failedQueue = [];

function processQueue(error, token = null) {
    failedQueue.forEach(({ resolve, reject }) => {
        if (error) {
            reject(error);
        } else {
            resolve(token);
        }
    });
    failedQueue = [];
}

async function refreshAccessToken() {
    const response = await fetch('/api/v1/auth/refresh', {
        method: 'POST',
        credentials: 'same-origin'
    });
    if (!response.ok) {
        throw new Error('Unable to refresh token');
    }
    const data = await response.json();
    setToken(data.access_token);
    return data.access_token;
}

async function apiFetch(url, options = {}) {
    const token = getToken();
    if (!token) {
        window.location.href = '/admin/login';
        return;
    }
    const headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
        ...options.headers
    };
    let response;
    try {
        response = await fetch(url, { ...options, headers });
    } catch (networkError) {
        alert('Сетевая ошибка. Проверьте подключение.');
        return null;
    }

    if (response.status === 401 && !options._retry) {
        if (!isRefreshing) {
            isRefreshing = true;
            try {
                const newToken = await refreshAccessToken();
                processQueue(null, newToken);
                headers['Authorization'] = 'Bearer ' + newToken;
                response = await fetch(url, { ...options, headers, _retry: true });
            } catch (error) {
                processQueue(error, null);
                clearToken();
                window.location.href = '/admin/login';
                return;
            } finally {
                isRefreshing = false;
            }
        } else {
            return new Promise((resolve, reject) => {
                failedQueue.push({ resolve, reject });
            }).then(token => {
                headers['Authorization'] = 'Bearer ' + token;
                return fetch(url, { ...options, headers });
            });
        }
    }

    if (response.status === 403) {
        alert('Недостаточно прав');
        return null;
    }

    if (!response.ok) {
        let errMsg = 'Произошла ошибка';
        try {
            const err = await response.json();
            errMsg = err.message || err.error || errMsg;
        } catch (e) {}
        alert(errMsg);
        return null;
    }

    return response.json();
}

// Логин
async function login(email, password) {
    const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password })
    });
    if (!response.ok) {
        const err = await response.json();
        throw new Error(err.error || 'Неверные учётные данные');
    }
    const data = await response.json();
    setToken(data.access_token);
    return data;
}

// Привязка событий
document.addEventListener('DOMContentLoaded', () => {
    if (window.location.pathname !== '/admin/login' && !isAuthenticated()) {
        window.location.href = '/admin/login';
        return;
    }

    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const email = document.getElementById('login-email').value;
            const password = document.getElementById('login-password').value;
            const errorEl = document.getElementById('login-error');
            errorEl.textContent = '';
            try {
                await login(email, password);
                window.location.href = '/admin';
            } catch (e) {
                errorEl.textContent = e.message;
            }
        });
    }

    const logoutBtn = document.getElementById('logout-btn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', logout);
    }

    const createUserForm = document.getElementById('create-user-form');
    if (createUserForm) createUserForm.addEventListener('submit', createUser);

    const editUserForm = document.getElementById('edit-user-form');
    if (editUserForm) editUserForm.addEventListener('submit', updateUserRoles);

    const createRoleForm = document.getElementById('create-role-form');
    if (createRoleForm) createRoleForm.addEventListener('submit', createRole);

    const editRoleForm = document.getElementById('edit-role-form');
    if (editRoleForm) editRoleForm.addEventListener('submit', updateRolePermissions);
});

// User actions (остались без изменений, кроме использования apiFetch)
async function createUser(event) {
    event.preventDefault();
    const form = document.getElementById('create-user-form');
    const formData = new FormData(form);
    const data = {
        email: formData.get('email'),
        password: formData.get('password'),
        is_active: formData.get('is_active') === 'on',
        roles: formData.getAll('roles')
    };
    const result = await apiFetch('/api/v1/admin/users', { method: 'POST', body: JSON.stringify(data) });
    if (result) window.location.href = '/admin/users';
}

async function deactivateUser(userId) {
    if (confirm('Деактивировать пользователя?')) {
        await apiFetch(`/api/v1/admin/users/${userId}/deactivate`, { method: 'POST' });
        location.reload();
    }
}

async function deleteUser(userId) {
    if (confirm('Удалить пользователя?')) {
        await apiFetch(`/api/v1/admin/users/${userId}`, { method: 'DELETE' });
        location.reload();
    }
}

async function updateUserRoles(event) {
    event.preventDefault();
    const form = document.getElementById('edit-user-form');
    const formData = new FormData(form);
    const userId = window.location.pathname.split('/').pop();
    const data = { roles: formData.getAll('roles') };
    await apiFetch(`/api/v1/admin/users/${userId}/roles`, { method: 'PUT', body: JSON.stringify(data) });
    window.location.href = '/admin/users';
}

async function createRole(event) {
    event.preventDefault();
    const form = document.getElementById('create-role-form');
    const formData = new FormData(form);
    const data = {
        name: formData.get('name'),
        description: formData.get('description'),
        permissions: formData.getAll('permissions')
    };
    const result = await apiFetch('/api/v1/admin/roles', { method: 'POST', body: JSON.stringify(data) });
    if (result) window.location.href = '/admin/roles';
}

async function updateRolePermissions(event) {
    event.preventDefault();
    const form = document.getElementById('edit-role-form');
    const formData = new FormData(form);
    const roleName = window.location.pathname.split('/').pop();
    const data = { permissions: formData.getAll('permissions') };
    await apiFetch(`/api/v1/admin/roles/${roleName}/permissions`, { method: 'PUT', body: JSON.stringify(data) });
    window.location.href = '/admin/roles';
}

async function deleteRole(roleName) {
    if (confirm(`Удалить роль "${roleName}"?`)) {
        await apiFetch(`/api/v1/admin/roles/${roleName}`, { method: 'DELETE' });
        location.reload();
    }
}
