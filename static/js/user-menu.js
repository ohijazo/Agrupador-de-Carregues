(() => {
  'use strict';
  document.addEventListener('click', (e) => {
    document.querySelectorAll('details.user-menu[open]').forEach((m) => {
      if (!m.contains(e.target)) m.open = false;
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      document.querySelectorAll('details.user-menu[open]').forEach((m) => {
        m.open = false;
      });
    }
  });
})();
