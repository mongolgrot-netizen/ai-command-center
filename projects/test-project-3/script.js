// Simple script for the "Начать" button
document.addEventListener('DOMContentLoaded', function () {
  const btn = document.getElementById('startBtn');
  btn.addEventListener('click', function () {
    alert('Кнопка "Начать" нажата!');
  });
});