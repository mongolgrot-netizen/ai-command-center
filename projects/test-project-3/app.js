document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('startBtn');
    if (btn) {
        btn.addEventListener('click', async function () {
            try {
                const response = await fetch('/api/start', {
                    method: 'GET',
                    headers: { 'Content-Type': 'application/json' }
                });
                const data = await response.json();
                alert(data.message || 'Кнопка нажата!');
            } catch (e) {
                // Если API недоступно, просто показываем стандартное сообщение
                alert('Кнопка нажата!');
            }
        });
    }
});