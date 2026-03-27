// Podflow Dashboard — Keyboard shortcuts and interactions

document.addEventListener('keydown', function(e) {
  // Skip if typing in an input
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch(e.key) {
    case '/':
      e.preventDefault();
      window.location.href = '/search';
      break;
    case 's':
      // Star the focused card
      const focused = document.querySelector('.card:hover .action-btn[title="Star"]');
      if (focused) focused.click();
      break;
  }
});

// Copy to clipboard helper
function copyInsight(text) {
  navigator.clipboard.writeText(text).then(() => {
    // Brief flash feedback
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✓';
    setTimeout(() => btn.textContent = orig, 1000);
  });
}
