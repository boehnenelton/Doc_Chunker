/* Doc_Chunker — app.js | Version: 1.0.0 | Elton Boehnen
   ES5-safe. No framework. No template literals. */

/* ── Drawer ─────────────────────────────────────────────────────── */
function openDrawer() {
  var drawer  = document.getElementById('drawer');
  var overlay = document.getElementById('drawer-overlay');
  if (drawer)  drawer.classList.add('open');
  if (overlay) overlay.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeDrawer() {
  var drawer  = document.getElementById('drawer');
  var overlay = document.getElementById('drawer-overlay');
  if (drawer)  drawer.classList.remove('open');
  if (overlay) overlay.classList.remove('open');
  document.body.style.overflow = '';
}

/* Close drawer on Escape key */
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeDrawer();
});

/* ── Reparent row toggle ─────────────────────────────────────────── */
function toggleReparent(chunkId) {
  var row = document.getElementById('reparent-' + chunkId);
  if (!row) return;
  row.classList.toggle('open');
}

/* ── Flash auto-dismiss (5 seconds) ─────────────────────────────── */
(function() {
  var flashes = document.querySelectorAll('.flash');
  for (var i = 0; i < flashes.length; i++) {
    (function(el) {
      setTimeout(function() {
        if (el && el.parentElement) el.remove();
      }, 5000);
    })(flashes[i]);
  }
})();
