(function () {
  'use strict';

  const html = document.documentElement;
  const body = document.body;
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const collapseButton = document.getElementById('sidebarCollapse');
  const mobileButton = document.getElementById('sidebarToggle');
  const themeButton = document.getElementById('themeToggle');
  const themeIcon = document.getElementById('themeIcon');

  const THEME_KEY = 'gideon-theme';
  const SIDEBAR_KEY = 'gideon-sidebar-collapsed';

  function applyTheme(theme) {
    html.setAttribute('data-bs-theme', theme);
    if (themeIcon) themeIcon.className = theme === 'dark' ? 'bi bi-sun-fill' : 'bi bi-moon-fill';
    localStorage.setItem(THEME_KEY, theme);
  }

  function setCollapsed(collapsed) {
    body.classList.toggle('sidebar-collapsed', collapsed);
    if (collapseButton) {
      collapseButton.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
      collapseButton.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
      collapseButton.innerHTML = collapsed ? '<i class="bi bi-layout-sidebar-inset-reverse"></i>' : '<i class="bi bi-layout-sidebar-inset"></i>';
    }
    localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0');
  }

  function closeMobileSidebar() {
    if (sidebar) sidebar.classList.remove('show');
    if (backdrop) backdrop.classList.remove('show');
  }

  const savedTheme = localStorage.getItem(THEME_KEY) || 'dark';
  applyTheme(savedTheme);
  setCollapsed(localStorage.getItem(SIDEBAR_KEY) === '1');

  if (themeButton) themeButton.addEventListener('click', function () {
    applyTheme(html.getAttribute('data-bs-theme') === 'dark' ? 'light' : 'dark');
  });
  if (collapseButton) collapseButton.addEventListener('click', function () {
    setCollapsed(!body.classList.contains('sidebar-collapsed'));
  });
  if (mobileButton) mobileButton.addEventListener('click', function () {
    if (sidebar) sidebar.classList.add('show');
    if (backdrop) backdrop.classList.add('show');
  });
  if (backdrop) backdrop.addEventListener('click', closeMobileSidebar);

  document.querySelectorAll('#sidebar .nav-link').forEach(function (link) {
    link.addEventListener('click', closeMobileSidebar);
  });

  document.querySelectorAll('.alert.alert-success, .alert.alert-info').forEach(function (el) {
    setTimeout(function () {
      if (window.bootstrap) bootstrap.Alert.getOrCreateInstance(el).close();
    }, 5000);
  });
})();
