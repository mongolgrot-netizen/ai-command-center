export default function App() {
  return (
    <section className="max-w-md w-full bg-gray-800 rounded-xl shadow-lg p-8 flex flex-col items-center space-y-6">
      <h1 className="text-3xl font-bold text-center text-white">Тестовый проект</h1>
      <p className="text-gray-300 text-center">Простое SPA с современным дизайном</p>
      <button
        className="px-6 py-3 bg-indigo-600 hover:bg-indigo-500 text-white font-medium rounded-lg transition-colors"
        onClick={() => alert('Кнопка нажата!')}
      >
        Нажми меня
      </button>
    </section>
  );
}
