document.addEventListener('DOMContentLoaded', function () {
    const btn = document.getElementById('startBtn');
    if (btn) {
        btn.addEventListener('click', function () {
            alert('Кнопка нажата!');
        });
    }
});