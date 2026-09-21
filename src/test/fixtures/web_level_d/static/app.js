let count = 0;
document.querySelector('#increment').addEventListener('click', () => {
  count += 1;
  document.querySelector('#count').textContent = String(count);
});
