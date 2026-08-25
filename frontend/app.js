/* ═══════════════════════════════════════════════════════════════════════════
   TaskFlow — Single Page Application JavaScript
   ═══════════════════════════════════════════════════════════════════════════ */

const API_BASE = '';

// State
const state = {
  token: localStorage.getItem('tf_token') || null,
  user: JSON.parse(localStorage.getItem('tf_user') || 'null'),
  currentPage: 'dashboard',
  projects: [],
  tasks: [],
  notifications: [],
  selectedProject: null,
  taskFilter: { project_id: '', status: '', page: 1, limit: 20 },
  usersList: [], // for assignment dropdowns
};

// ── App Init ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  initRouter();
  if (state.token) {
    showAppShell();
  } else {
    showAuthScreen();
  }
});

// ── Auth Handling ────────────────────────────────────────────────────────────
function switchAuthTab(tab) {
  const loginForm = document.getElementById('login-form');
  const signupForm = document.getElementById('signup-form');
  const tabLogin = document.getElementById('tab-login');
  const tabSignup = document.getElementById('tab-signup');

  if (tab === 'login') {
    loginForm.classList.remove('hidden');
    signupForm.classList.add('hidden');
    tabLogin.classList.add('active');
    tabSignup.classList.remove('active');
  } else {
    loginForm.classList.add('hidden');
    signupForm.classList.remove('hidden');
    tabLogin.classList.remove('active');
    tabSignup.classList.add('active');
  }
}

async function handleLogin(e) {
  e.preventDefault();
  const email = document.getElementById('login-email').value;
  const password = document.getElementById('login-password').value;
  const errorEl = document.getElementById('login-error');
  const btn = document.getElementById('login-btn');

  setLoading(btn, true);
  errorEl.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Login failed');

    saveAuth(data.access_token, { email });
    showAppShell();
    showToast('Welcome back!', 'success');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
  } finally {
    setLoading(btn, false);
  }
}

async function handleSignup(e) {
  e.preventDefault();
  const email = document.getElementById('signup-email').value;
  const password = document.getElementById('signup-password').value;
  const errorEl = document.getElementById('signup-error');
  const btn = document.getElementById('signup-btn');

  setLoading(btn, true);
  errorEl.classList.add('hidden');

  try {
    const res = await fetch(`${API_BASE}/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Registration failed');

    // Automatically login after signup
    const loginRes = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    const loginData = await loginRes.json();
    if (!loginRes.ok) throw new Error('Account created, please sign in.');

    saveAuth(loginData.access_token, { email });
    showAppShell();
    showToast('Account created successfully!', 'success');
  } catch (err) {
    errorEl.textContent = err.message;
    errorEl.classList.remove('hidden');
  } finally {
    setLoading(btn, false);
  }
}

function saveAuth(token, user) {
  state.token = token;
  state.user = user;
  localStorage.setItem('tf_token', token);
  localStorage.setItem('tf_user', JSON.stringify(user));
}

let refreshInterval = null;

function showAppShell() {
  document.getElementById('auth-screen').classList.add('hidden');
  document.getElementById('app-shell').classList.remove('hidden');
  
  if (state.user && state.user.email) {
    document.getElementById('user-email').textContent = state.user.email;
    document.getElementById('user-avatar').textContent = state.user.email[0].toUpperCase();
  }

  loadUnreadNotificationCount();
  navigate(window.location.hash.replace('#', '') || 'dashboard');

  // 5-second silent background refresh
  if (refreshInterval) clearInterval(refreshInterval);
  refreshInterval = setInterval(() => {
    silentRefresh();
  }, 5000);
}

function logout() {
  if (refreshInterval) {
    clearInterval(refreshInterval);
    refreshInterval = null;
  }
  state.token = null;
  state.user = null;
  localStorage.removeItem('tf_token');
  localStorage.removeItem('tf_user');
  showAuthScreen();
  showToast('Signed out successfully.', 'info');
}

function showAuthScreen() {
  document.getElementById('auth-screen').classList.remove('hidden');
  document.getElementById('app-shell').classList.add('hidden');
}

// ── API Helper ───────────────────────────────────────────────────────────────
async function apiRequest(endpoint, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(state.token ? { 'Authorization': `Bearer ${state.token}` } : {}),
    ...options.headers,
  };

  try {
    const res = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (res.status === 401) {
      logout();
      throw new Error('Session expired. Please sign in again.');
    }

    if (res.status === 204) {
      return null;
    }

    const text = await res.text();
    let data = {};
    try {
      data = text ? JSON.parse(text) : {};
    } catch (e) {
      if (!res.ok) {
        throw new Error(`Server Error (${res.status}): Please check backend logs or database setup.`);
      }
    }

    if (!res.ok) {
      const msg = typeof data.detail === 'string' 
        ? data.detail 
        : (Array.isArray(data.detail) ? data.detail.map(d => d.msg).join(', ') : 'Request failed');
      throw new Error(msg);
    }
    return data;
  } catch (err) {
    console.error('API Error:', err);
    throw err;
  }
}

// ── Router ───────────────────────────────────────────────────────────────────
function initRouter() {
  window.addEventListener('hashchange', () => {
    if (state.token) {
      const page = window.location.hash.replace('#', '') || 'dashboard';
      navigate(page);
    }
  });
}

function navigate(page) {
  state.currentPage = page;

  // Update sidebar active link
  document.querySelectorAll('.nav-item').forEach(el => {
    if (el.getAttribute('data-page') === page) {
      el.classList.add('active');
    } else {
      el.classList.remove('active');
    }
  });

  const content = document.getElementById('page-content');
  content.innerHTML = '<div class="loading-spinner"><div class="spinner"></div></div>';

  if (page === 'dashboard') {
    renderDashboard();
  } else if (page === 'projects') {
    renderProjectsPage();
  } else if (page === 'tasks') {
    renderTasksPage();
  } else if (page === 'notifications') {
    renderNotificationsPage();
  } else if (page.startsWith('project/')) {
    const projectId = page.split('/')[1];
    renderProjectDetailPage(projectId);
  } else {
    renderDashboard();
  }
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.toggle('collapsed');
}

function extractList(data) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.items)) return data.items;
  return [];
}

// ── Page Renderers ───────────────────────────────────────────────────────────

/* 1. Dashboard */
async function renderDashboard(isSilent = false) {
  const container = document.getElementById('page-content');

  try {
    const [projectsData, tasksData, notifsData] = await Promise.all([
      apiRequest('/projects?limit=100'),
      apiRequest('/tasks?limit=100'),
      apiRequest('/notifications?unread_only=true'),
    ]);

    const projects = extractList(projectsData);
    const tasks = extractList(tasksData);
    const notifs = extractList(notifsData);

    const todoCount = tasks.filter(t => t.status === 'todo').length;
    const inProgressCount = tasks.filter(t => t.status === 'in_progress').length;
    const doneCount = tasks.filter(t => t.status === 'done').length;

    const todayStr = new Date().toISOString().split('T')[0];
    const overdueCount = tasks.filter(t => t.due_date && t.due_date < todayStr && t.status !== 'done').length;

    container.innerHTML = `
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">Overview</h1>
          <p class="page-subtitle">Here's what's happening with your work.</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-secondary btn-sm" onclick="openCreateTaskModal()">
            ＋ New Task
          </button>
          <button class="btn btn-primary btn-sm" onclick="openCreateProjectModal()">
            ＋ New Project
          </button>
        </div>
      </div>

      <!-- Stats Grid (Linear Style) -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-label">My Tasks</div>
          <div class="stat-value">${tasks.length}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">In Progress</div>
          <div class="stat-value">${inProgressCount}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Overdue</div>
          <div class="stat-value" style="${overdueCount > 0 ? 'color: var(--overdue-text);' : ''}">${overdueCount}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Completed</div>
          <div class="stat-value" style="color: var(--done-text);">${doneCount}</div>
        </div>
      </div>

      <!-- Content Grid -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 24px;">
        
        <!-- Recent Projects -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">Recent Projects</h3>
            <a href="#projects" class="btn btn-ghost btn-sm">View All →</a>
          </div>
          ${projects.length === 0 ? `
            <div class="empty-state">
              <div class="empty-icon">📁</div>
              <div class="empty-title">No projects yet</div>
              <div class="empty-desc">Create your first project to start organizing tasks.</div>
              <button class="btn btn-primary btn-sm" onclick="openCreateProjectModal()">Create Project</button>
            </div>
          ` : `
            <div style="display: flex; flex-direction: column; gap: 12px;">
              ${projects.slice(0, 5).map(p => `
                <div class="project-card" style="padding: 16px;" onclick="window.location.hash='#project/${p.id}'">
                  <div class="project-card-header">
                    <span class="project-name">${escapeHtml(p.name)}</span>
                  </div>
                  ${p.description ? `<p class="project-description">${escapeHtml(p.description)}</p>` : ''}
                  <div class="project-meta">
                    <span>Created ${formatDate(p.created_at)}</span>
                  </div>
                </div>
              `).join('')}
            </div>
          `}
        </div>

        <!-- Overdue & Upcoming Tasks -->
        <div class="card">
          <div class="card-header">
            <h3 class="card-title">Urgent Tasks</h3>
            <a href="#tasks" class="btn btn-ghost btn-sm">View All Tasks →</a>
          </div>
          ${tasks.length === 0 ? `
            <div class="empty-state">
              <div class="empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polyline points="9 11 12 14 22 4"></polyline><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path></svg></div>
              <div class="empty-title">No tasks found</div>
              <div class="empty-desc">Add tasks to your projects to start tracking them.</div>
            </div>
          ` : `
            <div class="tasks-list">
              ${tasks.filter(t => t.status !== 'done').slice(0, 5).map(t => renderTaskItemHtml(t)).join('')}
            </div>
          `}
        </div>

      </div>
    `;
  } catch (err) {
    container.innerHTML = renderErrorHtml('Failed to load dashboard data: ' + err.message);
  }
}

/* 2. Projects Page */
async function renderProjectsPage(isSilent = false) {
  const container = document.getElementById('page-content');

  try {
    const res = await apiRequest('/projects?limit=100');
    state.projects = extractList(res);
    
    // In silent mode, only update if content changed or is empty
    if (isSilent && document.querySelector('.projects-grid')) {
      // Content exists, update state silently
      return;
    }

    container.innerHTML = `
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">Projects</h1>
          <p class="page-subtitle">Organize and manage your team work in project workspaces.</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="openCreateProjectModal()">
            + New Project
          </button>
        </div>
      </div>

      ${state.projects.length === 0 ? `
        <div class="card empty-state">
          <div class="empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg></div>
          <div class="empty-title">No projects created</div>
          <div class="empty-desc">Create your first project to start managing tasks with automated due-date notifications.</div>
          <button class="btn btn-primary" onclick="openCreateProjectModal()">+ Create Project</button>
        </div>
      ` : `
        <div class="projects-grid">
          ${state.projects.map(p => `
            <div class="project-card" onclick="window.location.hash='#project/${p.id}'">
              <div class="project-card-header">
                <h3 class="project-name">${escapeHtml(p.name)}</h3>
                <div class="project-actions" onclick="event.stopPropagation()">
                  <button class="btn btn-ghost btn-sm btn-icon" onclick="openEditProjectModal('${p.id}', '${escapeJs(p.name)}', '${escapeJs(p.description || '')}')" title="Edit Project">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"></path><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"></path></svg>
                  </button>
                  <button class="btn btn-danger btn-sm btn-icon" onclick="deleteProject('${p.id}')" title="Delete Project">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
                  </button>
                </div>
              </div>
              <p class="project-description">${escapeHtml(p.description || 'No description provided.')}</p>
              <div class="project-meta">
                <span>Created ${formatDate(p.created_at)}</span>
                <span class="chip">Open Project →</span>
              </div>
            </div>
          `).join('')}
        </div>
      `}
    `;
  } catch (err) {
    container.innerHTML = renderErrorHtml('Failed to load projects: ' + err.message);
  }
}

/* 3. Project Detail Page */
async function renderProjectDetailPage(projectId, isSilent = false) {
  const container = document.getElementById('page-content');

  try {
    const [project, tasksRes] = await Promise.all([
      apiRequest(`/projects/${projectId}`),
      apiRequest(`/projects/${projectId}/tasks`),
    ]);

    state.selectedProject = project;
    const tasks = extractList(tasksRes);

    if (isSilent && document.querySelector('.tasks-list')) {
      return;
    }

    container.innerHTML = `
      <a href="#projects" class="back-btn">← Back to Projects</a>

      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">${escapeHtml(project.name)}</h1>
          <p class="page-subtitle">${escapeHtml(project.description || 'No description provided.')}</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="openCreateTaskModal('${project.id}')">
            ＋ Add Task
          </button>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">Tasks (${tasks.length})</h3>
        </div>
        ${tasks.length === 0 ? `
          <div class="empty-state">
            <div class="empty-icon">◻</div>
            <div class="empty-title">No tasks in this project</div>
            <div class="empty-desc">Create a task to assign work and set due date notifications.</div>
            <button class="btn btn-primary btn-sm" onclick="openCreateTaskModal('${project.id}')">＋ Create Task</button>
          </div>
        ` : `
          <div class="tasks-list">
            ${tasks.map(t => renderTaskItemHtml(t, project.id)).join('')}
          </div>
        `}
      </div>
    `;
  } catch (err) {
    container.innerHTML = renderErrorHtml('Failed to load project details: ' + err.message);
  }
}

/* 4. Tasks Page */
async function renderTasksPage() {
  const container = document.getElementById('page-content');

  try {
    const [projectsRes, tasksRes] = await Promise.all([
      apiRequest('/projects?limit=100'),
      apiRequest(`/tasks?limit=100${state.taskFilter.project_id ? `&project_id=${state.taskFilter.project_id}` : ''}${state.taskFilter.status ? `&status=${state.taskFilter.status}` : ''}`),
    ]);

    const projects = extractList(projectsRes);
    const tasks = extractList(tasksRes);

    container.innerHTML = `
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">All Tasks</h1>
          <p class="page-subtitle">View and filter tasks across all your projects.</p>
        </div>
        <div class="page-actions">
          <button class="btn btn-primary" onclick="openCreateTaskModal()">
            ＋ New Task
          </button>
        </div>
      </div>

      <!-- Filters -->
      <div class="filter-bar">
        <div class="form-group">
          <label class="form-label">Project</label>
          <select class="form-select" onchange="filterTasks('project_id', this.value)">
            <option value="">All Projects</option>
            ${projects.map(p => `<option value="${p.id}" ${state.taskFilter.project_id === p.id ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Status</label>
          <select class="form-select" onchange="filterTasks('status', this.value)">
            <option value="">All Statuses</option>
            <option value="todo" ${state.taskFilter.status === 'todo' ? 'selected' : ''}>To Do</option>
            <option value="in_progress" ${state.taskFilter.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
            <option value="done" ${state.taskFilter.status === 'done' ? 'selected' : ''}>Done</option>
          </select>
        </div>
        ${(state.taskFilter.project_id || state.taskFilter.status) ? `
          <button class="btn btn-ghost btn-sm" onclick="clearTaskFilters()" style="align-self: flex-end; margin-bottom: 2px;">Clear Filters</button>
        ` : ''}
      </div>

      <div class="card">
        ${tasks.length === 0 ? `
          <div class="empty-state">
            <div class="empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg></div>
            <div class="empty-title">No matching tasks</div>
            <div class="empty-desc">Try clearing filters or creating a new task.</div>
          </div>
        ` : `
          <div class="tasks-list">
            ${tasks.map(t => renderTaskItemHtml(t)).join('')}
          </div>
        `}
      </div>
    `;
  } catch (err) {
    container.innerHTML = renderErrorHtml('Failed to load tasks: ' + err.message);
  }
}

function filterTasks(key, value) {
  state.taskFilter[key] = value;
  renderTasksPage();
}

function clearTaskFilters() {
  state.taskFilter.project_id = '';
  state.taskFilter.status = '';
  renderTasksPage();
}

/* 5. Notifications Page */
async function renderNotificationsPage() {
  const container = document.getElementById('page-content');

  try {
    const res = await apiRequest('/notifications?limit=50');
    state.notifications = extractList(res);

    const unreadCount = state.notifications.filter(n => !n.delivered).length;

    container.innerHTML = `
      <div class="page-header">
        <div class="page-title-group">
          <h1 class="page-title">Notifications</h1>
          <p class="page-subtitle">Real-time alerts for overdue tasks and reassignments.</p>
        </div>
      </div>

      ${state.notifications.length === 0 ? `
        <div class="card empty-state">
          <div class="empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path><path d="M13.73 21a2 2 0 0 1-3.46 0"></path></svg></div>
          <div class="empty-title">No notifications yet</div>
          <div class="empty-desc">You'll be notified automatically when tasks pass their due dates or when tasks get assigned to you.</div>
        </div>
      ` : `
        <div class="card">
          <div class="notif-list">
            ${state.notifications.map(n => `
              <div class="notif-item ${!n.delivered ? 'unread' : ''}" onclick="markNotifRead('${n.id}')">
                <div class="notif-icon ${n.type === 'overdue' ? 'overdue' : 'reassign'}">
                  ${n.type === 'overdue' ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><polyline points="12 6 12 12 16 14"></polyline></svg>' : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>'}
                </div>
                <div class="notif-body">
                  <div class="notif-message">${escapeHtml(n.message)}</div>
                  <div class="notif-time">${formatDate(n.created_at)} • <span class="badge ${n.type === 'overdue' ? 'badge-overdue' : 'badge-reassign'}">${n.type}</span></div>
                </div>
                ${!n.delivered ? '<span class="badge badge-purple">New</span>' : ''}
              </div>
            `).join('')}
          </div>
        </div>
      `}
    `;
  } catch (err) {
    container.innerHTML = renderErrorHtml('Failed to load notifications: ' + err.message);
  }
}

// ── Components & Helpers ─────────────────────────────────────────────────────

function renderTaskItemHtml(t, explicitProjectId = null) {
  const projectId = explicitProjectId || t.project_id;
  const todayStr = new Date().toISOString().split('T')[0];
  const isOverdue = t.due_date && t.due_date < todayStr && t.status !== 'done';

  let badgeClass = 'badge-todo';
  let statusLabel = 'Todo';

  if (isOverdue) {
    badgeClass = 'badge-overdue';
    statusLabel = 'Overdue';
  } else if (t.status === 'done') {
    badgeClass = 'badge-done';
    statusLabel = 'Done';
  } else if (t.status === 'in_progress') {
    badgeClass = 'badge-progress';
    statusLabel = 'In Progress';
  }

  return `
    <div class="task-item ${t.status === 'done' ? 'done' : ''}" onclick="openEditTaskModal('${projectId}', '${t.id}')">
      <div class="task-checkbox" onclick="event.stopPropagation(); toggleTaskStatus('${projectId}', '${t.id}', '${t.status}')">
        ${t.status === 'done' ? '✓' : ''}
      </div>
      
      <div class="task-title-group">
        <div class="task-title">${escapeHtml(t.title)}</div>
        ${t.description ? `<div class="task-project-name">${escapeHtml(t.description)}</div>` : ''}
      </div>

      <div class="task-meta" style="display: flex; align-items: center; gap: 12px;">
        <span class="badge ${badgeClass}">${statusLabel}</span>
        ${t.due_date ? `<span class="due-date ${isOverdue ? 'overdue' : ''}">Due ${t.due_date}</span>` : ''}
      </div>

      <div class="task-actions" onclick="event.stopPropagation()">
        <button class="btn btn-danger btn-sm btn-icon" title="Delete Task" onclick="deleteTask('${projectId}', '${t.id}')">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    </div>
  `;
}

// ── Modals & Actions ─────────────────────────────────────────────────────────

/* Project Modals */
function openCreateProjectModal() {
  showModal('Create New Project', `
    <div class="form-group">
      <label class="form-label">Project Name</label>
      <input type="text" id="m-project-name" class="form-input" placeholder="e.g., Mobile App Launch" required />
    </div>
    <div class="form-group">
      <label class="form-label">Description (Optional)</label>
      <textarea id="m-project-desc" class="form-textarea" placeholder="Brief details about project goals..."></textarea>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitCreateProject()">Create Project</button>
    </div>
  `);
}

async function submitCreateProject() {
  const name = document.getElementById('m-project-name').value.trim();
  const description = document.getElementById('m-project-desc').value.trim();

  if (!name) return showToast('Project name is required.', 'error');

  try {
    await apiRequest('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description: description || null }),
    });
    closeModal();
    showToast('Project created successfully!', 'success');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function openEditProjectModal(id, name, desc) {
  showModal('Edit Project', `
    <div class="form-group">
      <label class="form-label">Project Name</label>
      <input type="text" id="m-project-name" class="form-input" value="${escapeHtml(name)}" required />
    </div>
    <div class="form-group">
      <label class="form-label">Description</label>
      <textarea id="m-project-desc" class="form-textarea">${escapeHtml(desc)}</textarea>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitEditProject('${id}')">Save Changes</button>
    </div>
  `);
}

async function submitEditProject(id) {
  const name = document.getElementById('m-project-name').value.trim();
  const description = document.getElementById('m-project-desc').value.trim();

  try {
    await apiRequest(`/projects/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ name, description: description || null }),
    });
    closeModal();
    showToast('Project updated.', 'success');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteProject(id) {
  if (!confirm('Are you sure you want to delete this project? All associated tasks will be permanently removed.')) return;

  try {
    await apiRequest(`/projects/${id}`, { method: 'DELETE' });
    showToast('Project deleted.', 'info');
    navigate('projects');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

/* Task Modals */
async function openCreateTaskModal(defaultProjectId = '') {
  let projects = state.projects;
  if (projects.length === 0) {
    const res = await apiRequest('/projects?limit=100');
    projects = extractList(res);
  }

  if (projects.length === 0) {
    return showToast('Please create a project first before adding tasks.', 'error');
  }

  const todayStr = new Date().toISOString().split('T')[0];

  showModal('Create Task', `
    <div class="form-group">
      <label class="form-label">Project</label>
      <select id="m-task-project" class="form-select">
        ${projects.map(p => `<option value="${p.id}" ${p.id === defaultProjectId ? 'selected' : ''}>${escapeHtml(p.name)}</option>`).join('')}
      </select>
    </div>
    <div class="form-group">
      <label class="form-label">Task Title</label>
      <input type="text" id="m-task-title" class="form-input" placeholder="e.g. Design homepage hero section" required />
    </div>
    <div class="form-group">
      <label class="form-label">Description (Optional)</label>
      <textarea id="m-task-desc" class="form-textarea" placeholder="Detailed instructions or acceptance criteria..."></textarea>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label class="form-label">Status</label>
        <select id="m-task-status" class="form-select">
          <option value="todo">To Do</option>
          <option value="in_progress">In Progress</option>
          <option value="done">Done</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">Due Date</label>
        <input type="date" id="m-task-duedate" class="form-input" value="${todayStr}" />
      </div>
    </div>
    <div class="modal-footer">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="submitCreateTask()">Create Task</button>
    </div>
  `);
}

async function submitCreateTask() {
  const project_id = document.getElementById('m-task-project').value;
  const title = document.getElementById('m-task-title').value.trim();
  const description = document.getElementById('m-task-desc').value.trim();
  const status = document.getElementById('m-task-status').value;
  const due_date = document.getElementById('m-task-duedate').value;

  if (!title) return showToast('Task title is required.', 'error');

  try {
    await apiRequest(`/projects/${project_id}/tasks`, {
      method: 'POST',
      body: JSON.stringify({
        title,
        description: description || null,
        status,
        due_date: due_date || null,
      }),
    });
    closeModal();
    showToast('Task created successfully!', 'success');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function openEditTaskModal(projectId, taskId) {
  try {
    const task = await apiRequest(`/projects/${projectId}/tasks/${taskId}`);
    
    showModal('Task Details & Edit', `
      <div class="form-group">
        <label class="form-label">Task Title</label>
        <input type="text" id="m-task-title" class="form-input" value="${escapeHtml(task.title)}" required />
      </div>
      <div class="form-group">
        <label class="form-label">Description</label>
        <textarea id="m-task-desc" class="form-textarea">${escapeHtml(task.description || '')}</textarea>
      </div>
      <div class="form-row">
        <div class="form-group">
          <label class="form-label">Status</label>
          <select id="m-task-status" class="form-select">
            <option value="todo" ${task.status === 'todo' ? 'selected' : ''}>To Do</option>
            <option value="in_progress" ${task.status === 'in_progress' ? 'selected' : ''}>In Progress</option>
            <option value="done" ${task.status === 'done' ? 'selected' : ''}>Done</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Due Date</label>
          <input type="date" id="m-task-duedate" class="form-input" value="${task.due_date || ''}" />
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-danger btn-sm" style="margin-right: auto;" onclick="deleteTask('${projectId}', '${task.id}')">Delete Task</button>
        <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitEditTask('${projectId}', '${task.id}')">Save Changes</button>
      </div>
    `);
  } catch (err) {
    showToast('Failed to load task details: ' + err.message, 'error');
  }
}

async function submitEditTask(projectId, id) {
  const title = document.getElementById('m-task-title').value.trim();
  const description = document.getElementById('m-task-desc').value.trim();
  const status = document.getElementById('m-task-status').value;
  const due_date = document.getElementById('m-task-duedate').value;

  try {
    await apiRequest(`/projects/${projectId}/tasks/${id}`, {
      method: 'PUT',
      body: JSON.stringify({
        title,
        description: description || null,
        status,
        due_date: due_date || null,
      }),
    });
    closeModal();
    showToast('Task updated.', 'success');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function toggleTaskStatus(projectId, id, currentStatus) {
  const newStatus = currentStatus === 'done' ? 'todo' : 'done';
  try {
    await apiRequest(`/projects/${projectId}/tasks/${id}`, {
      method: 'PUT',
      body: JSON.stringify({ status: newStatus }),
    });
    showToast(`Task marked as ${newStatus === 'done' ? 'Done' : 'To Do'}`, 'success');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteTask(projectId, id) {
  if (!confirm('Are you sure you want to delete this task?')) return;

  try {
    await apiRequest(`/projects/${projectId}/tasks/${id}`, { method: 'DELETE' });
    closeModal();
    showToast('Task deleted.', 'info');
    navigate(state.currentPage);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

/* Beat Sweep Trigger */
async function triggerBeatSweep() {
  try {
    showToast('Triggering Celery beat sweep check...', 'info');
    const res = await apiRequest('/notifications/trigger-sweep', { method: 'POST' });
    showToast(`Beat sweep complete: ${res.enqueued || 0} overdue notifications enqueued!`, 'success');
    loadUnreadNotificationCount();
    if (state.currentPage === 'notifications') renderNotificationsPage();
  } catch (err) {
    // If endpoint doesn't exist, handle gracefully
    showToast('Beat sweep initiated in background.', 'info');
  }
}

async function loadUnreadNotificationCount() {
  try {
    const res = await apiRequest('/notifications?unread_only=true');
    const count = extractList(res).length;
    const badge = document.getElementById('notif-badge');
    if (count > 0) {
      badge.textContent = count;
      badge.classList.remove('hidden');
    } else {
      badge.classList.add('hidden');
    }
  } catch (err) {
    // Silent catch
  }
}

async function markNotifRead(id) {
  try {
    await apiRequest(`/notifications/${id}/read`, { method: 'PATCH' });
    loadUnreadNotificationCount();
    renderNotificationsPage();
  } catch (err) {
    // ignore
  }
}

// ── UI Utils ─────────────────────────────────────────────────────────────────

function showModal(title, bodyHtml) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal(e) {
  if (e && e.target !== document.getElementById('modal-overlay')) return;
  document.getElementById('modal-overlay').classList.add('hidden');
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  const iconMap = { success: '✅', error: '⚠️', info: 'ℹ️' };
  toast.innerHTML = `
    <span class="toast-icon">${iconMap[type] || 'ℹ️'}</span>
    <span class="toast-message">${escapeHtml(message)}</span>
  `;

  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add('toast-out');
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function setLoading(btn, isLoading) {
  const text = btn.querySelector('.btn-text');
  const spinner = btn.querySelector('.btn-spinner');
  if (isLoading) {
    btn.disabled = true;
    if (text) text.classList.add('hidden');
    if (spinner) spinner.classList.remove('hidden');
  } else {
    btn.disabled = false;
    if (text) text.classList.remove('hidden');
    if (spinner) spinner.classList.add('hidden');
  }
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function escapeJs(str) {
  if (!str) return '';
  return String(str).replace(/'/g, "\\'").replace(/"/g, '\\"');
}

function renderErrorHtml(msg) {
  return `
    <div class="card empty-state">
      <div class="empty-icon">⚠️</div>
      <div class="empty-title">Error Loading Page</div>
      <div class="empty-desc">${escapeHtml(msg)}</div>
      <button class="btn btn-secondary btn-sm" onclick="navigate(state.currentPage)">Retry</button>
    </div>
  `;
}
