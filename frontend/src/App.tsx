import { useEffect, useState } from 'react' // Импортируем хуки React для управления состоянием и побочными эффектами
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet' // Компоненты карты из библиотеки react-leaflet
import L from 'leaflet' // Основная библиотека Leaflet для создания кастомных иконок
import axios from 'axios' // HTTP-клиент для запросов к бэкенду
import StatsPanel from './StatsPanel' // Импортируем компонент панели статистики справа

// Единый размер шрифта для всего приложения
const FONT_SIZE = '12px'

// Интерфейс для кластера
interface Cluster {
  id: number
  center_lat: number
  center_lon: number
  color: string
  accidents_count: number
  killed_total: number
  injured_total: number
  main_dtp_type: string
  main_district: string
  main_lighting: string
  night_pct: number
}

// Функция для создания цветных маркеров
const createColoredIcon = (color: string, accidentsCount: number) => {
  const minSize = 8 // Минимальный размер маркера в пикселях (для кластеров с 3 ДТП)
  const maxSize = 32 // Максимальный размер маркера в пикселях (для крупных кластеров)

  // Вычисляем размер маркера по логарифмической шкале
  // Логарифм нужен, чтобы маркеры не становились гигантскими при большом количестве ДТП
  const size = Math.round(minSize + (maxSize - minSize) * Math.log(accidentsCount) / Math.log(30))

  // Ограничиваем размер: не меньше minSize и не больше maxSize
  const finalSize = Math.min(Math.max(size, minSize), maxSize)

  // Создаём кастомную иконку Leaflet с помощью HTML и CSS
  return L.divIcon({
    className: 'custom-div-icon', // CSS-класс для иконки
    html: `<div style="background-color: ${color}; width: ${finalSize}px; height: ${finalSize}px; border-radius: 50%; border: 2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>`,
    iconSize: [finalSize, finalSize], // Размер иконки в пикселях
    iconAnchor: [finalSize / 2, finalSize / 2], // Точка привязки иконки к координатам (центр круга)
  })
}

// Функция для конвертации формата "MM.YYYY" в "YYYY-MM"
const convertMonthFormat = (monthStr: string): string => {
  const [month, year] = monthStr.split('.') // Разделяем строку по точке
  return `${year}-${month}` // Собираем в формат "YYYY-MM" (так требует бэкенд)
}

// Функция для конвертации формата "YYYY-MM" в "MM.YYYY"
const convertToDisplayFormat = (monthStr: string): string => {
  const [year, month] = monthStr.split('-') // Разделяем строку по дефису
  return `${month}.${year}` // Собираем в формат "MM.YYYY" (для отображения)
}

function App() {
  const [clusters, setClusters] = useState<Cluster[]>([]) // Список кластеров, полученных с бэкенда
  const [loading, setLoading] = useState(true) // Индикатор загрузки данных

  // Состояние для выбранного месяца (null = все месяцы)
  const [selectedMonth, setSelectedMonth] = useState<string | null>(null)

  // Список доступных месяцев (отсортированный по убыванию)
  const [availableMonths, setAvailableMonths] = useState<string[]>([])

  // ============================================================
  // СОСТОЯНИЯ ДЛЯ ИИ-РЕКОМЕНДАЦИЙ
  // ============================================================
  // Словарь рекомендаций: ключ — ID кластера, значение — текст рекомендации
  // Храним в словаре, чтобы не загружать повторно при открытии попапа
  const [recommendations, setRecommendations] = useState<{ [key: number]: string }>({})

  // ID кластера, для которого сейчас загружается рекомендация (null — ничего не загружается)
  const [loadingRecommendation, setLoadingRecommendation] = useState<number | null>(null)

  // ============================================================
  // ФУНКЦИЯ ПОЛУЧЕНИЯ РЕКОМЕНДАЦИИ ИИ
  // ============================================================
  // Функция для получения рекомендации ИИ для конкретного кластера
  const fetchRecommendation = async (clusterId: number) => {
    // Если рекомендация уже загружена — не загружаем снова (экономим ресурсы)
    if (recommendations[clusterId]) return

    // Устанавливаем индикатор загрузки для конкретного кластера
    setLoadingRecommendation(clusterId)

    try {
      // Отправляем GET-запрос на бэкенд с ID кластера
      const response = await axios.get(`http://localhost:8000/api/recommendation/${clusterId}`)

      // Сохраняем рекомендацию в словарь (предыдущие рекомендации сохраняются)
      setRecommendations(prev => ({
        ...prev,
        [clusterId]: response.data.recommendation
      }))
    } catch (error) {
      console.error('Ошибка загрузки рекомендации:', error) // Выводим ошибку в консоль
    } finally {
      // Скрываем индикатор загрузки (в любом случае — успех или ошибка)
      setLoadingRecommendation(null)
    }
  }

  // ============================================================
  // ЗАГРУЗКА СПИСКА ДОСТУПНЫХ МЕСЯЦЕВ
  // ============================================================
  // Загружаем список доступных месяцев из статистики (один раз при монтировании)
  useEffect(() => {
    axios.get('http://localhost:8000/api/stats') // Запрашиваем общую статистику
      .then(response => {
        // Извлекаем месяцы из статистики и сортируем по убыванию
        const months = response.data.monthly
          .map((m: any) => convertMonthFormat(m.month)) // Конвертируем "MM.YYYY" в "YYYY-MM"
          .sort((a: string, b: string) => b.localeCompare(a)) // Сортируем по убыванию (сначала 2026, потом 2025)
        setAvailableMonths(months) // Сохраняем список месяцев в состояние
      })
      .catch(error => {
        console.error('Ошибка загрузки месяцев:', error) // Выводим ошибку в консоль
      })
  }, []) // Пустой массив — эффект выполняется только при первом рендере

  // ============================================================
  // ЗАГРУЗКА КЛАСТЕРОВ С ЗАДЕРЖКОЙ (DEBOUNCE)
  // ============================================================
  // Загружаем кластеры при изменении выбранного месяца
  // Используем задержку 1 секунду, чтобы не отправлять запросы при каждом движении ползунка
  useEffect(() => {
    // Устанавливаем таймер на 1 секунду (1000 миллисекунд)
    const timer = setTimeout(() => {
      setLoading(true) // Показываем индикатор загрузки

      // Формируем URL с параметром month (если выбран конкретный месяц)
      const url = selectedMonth
        ? `http://localhost:8000/api/clusters?month=${selectedMonth}` // URL с фильтром по месяцу
        : 'http://localhost:8000/api/clusters' // URL без фильтра (все месяцы)

      axios.get(url) // Отправляем GET-запрос на бэкенд
        .then(response => {
          setClusters(response.data.clusters) // Сохраняем список кластеров
          setLoading(false) // Скрываем индикатор загрузки
        })
        .catch(error => {
          console.error('Ошибка загрузки данных:', error) // Выводим ошибку в консоль
          setLoading(false) // Всё равно скрываем индикатор загрузки
        })
    }, 1000) // Задержка 1 секунда перед отправкой запроса

    // Функция очистки: если selectedMonth изменился раньше, чем прошли 3 секунды,
    // отменяем предыдущий таймер, чтобы не делать лишний запрос на бэкенд
    return () => clearTimeout(timer)
  }, [selectedMonth]) // Перезагружаем при изменении selectedMonth

  // ============================================================
  // ОБРАБОТЧИК ИЗМЕНЕНИЯ СЛАЙДЕРА
  // ============================================================
  // Обработчик изменения слайдера
  const handleSliderChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const index = parseInt(event.target.value) // Получаем позицию ползунка (0-N)
    if (index === 0) {
      setSelectedMonth(null) // Позиция 0 = "Все месяцы" (без фильтра)
    } else {
      setSelectedMonth(availableMonths[index - 1]) // Позиция 1+ = конкретный месяц (индекс -1, т.к. 0 зарезервирован)
    }
  }

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100%' }}>
      {/* Карта */}
      <div style={{ flex: 1, height: '100%', position: 'relative' }}>
        {/* ============================================================ */}
        {/* TIMELINE SLIDER (внизу слева, компактный) */}
        {/* ============================================================ */}
        <div style={{
          position: 'absolute', // Абсолютное позиционирование поверх карты
          bottom: '20px', // Отступ снизу
          left: '20px', // Отступ слева
          zIndex: 1000, // Поверх карты
          backgroundColor: '#f8f9fa', // Светло-серый фон
          padding: '8px 12px', // Внутренние отступы
          borderRadius: '4px', // Скруглённые углы
          border: '1px solid #dee2e6', // Тонкая серая граница
          fontFamily: 'Arial, sans-serif', // Шрифт
          minWidth: '250px', // Минимальная ширина
          fontSize: FONT_SIZE // Единый размер шрифта
        }}>
          <div style={{ marginBottom: '6px', color: '#000' }}>
            <b>Период:</b> {selectedMonth ? convertToDisplayFormat(selectedMonth) : 'Все месяцы'}
          </div>
          <input
            type="range" // Ползунок (слайдер)
            min="0" // Минимальное значение (Все месяцы)
            max={availableMonths.length} // Максимальное значение (количество месяцев)
            value={selectedMonth ? availableMonths.indexOf(selectedMonth) + 1 : 0} // Текущая позиция
            onChange={handleSliderChange} // Обработчик изменения
            style={{
              width: '100%', // На всю ширину контейнера
              cursor: 'pointer', // Курсор-указатель
              height: '4px' // Тонкий ползунок
            }}
          />
          <div style={{
            display: 'flex', // Flex-контейнер для подписей
            justifyContent: 'space-between', // Распределить по краям
            color: '#000', // Чёрный текст
            marginTop: '4px' // Отступ сверху
          }}>
            <span>Все</span> {/* Левая подпись */}
            <span>{availableMonths.length > 0 ? convertToDisplayFormat(availableMonths[0]) : ''}</span> {/* Правая подпись (самый старый месяц) */}
          </div>
        </div>

        {/* Карта */}
        <MapContainer center={[55.78, 49.12]} zoom={9} style={{ height: '100%', width: '100%' }}>
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          {loading ? (
            <div style={{ padding: '20px', fontSize: FONT_SIZE }}>Загрузка...</div>
          ) : (
            clusters.map(cluster => (
              <Marker
                key={cluster.id}
                position={[cluster.center_lat, cluster.center_lon]}
                icon={createColoredIcon(cluster.color, cluster.accidents_count)}
              >
                <Popup>
                  <div style={{ minWidth: '200px', fontSize: FONT_SIZE }}>
                    <h3 style={{ margin: '0 0 10px 0', color: cluster.color, fontSize: FONT_SIZE, fontWeight: 'bold' }}>
                      Очаг #{cluster.id + 1}
                    </h3>
                    <p style={{ margin: '4px 0' }}><b>Район:</b> {cluster.main_district}</p>
                    <p style={{ margin: '4px 0' }}><b>Всего ДТП:</b> {cluster.accidents_count}</p>
                    <p style={{ margin: '4px 0' }}><b>Погибло:</b> {cluster.killed_total}</p>
                    <p style={{ margin: '4px 0' }}><b>Ранено:</b> {cluster.injured_total}</p>
                    <p style={{ margin: '4px 0' }}><b>Тип:</b> {cluster.main_dtp_type}</p>
                    <p style={{ margin: '4px 0' }}><b>Освещение:</b> {cluster.main_lighting}</p>
                    <p style={{ margin: '4px 0' }}><b>Ночные ДТП:</b> {cluster.night_pct}%</p>

                    {/* ============================================================ */}
                    {/* КНОПКИ ДЕЙСТВИЙ */}
                    {/* ============================================================ */}
                    <div style={{ marginTop: '10px', paddingTop: '10px', borderTop: '1px solid #ddd' }}>
                      {/* Кнопка Яндекс.Панорамы */}
                      <a
                        href={`https://yandex.ru/maps/?ll=${cluster.center_lon},${cluster.center_lat}&z=18&l=stv&panorama[point]=${cluster.center_lon},${cluster.center_lat}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{
                          display: 'block',
                          width: '100%',
                          padding: '8px 10px',
                          backgroundColor: '#ffcc00', // Жёлтый цвет (бренд Яндекса)
                          color: '#000',
                          textDecoration: 'none',
                          borderRadius: '4px',
                          fontWeight: 'bold',
                          textAlign: 'center',
                          boxSizing: 'border-box',
                          marginBottom: '10px', // Отступ до кнопки ИИ
                          fontSize: FONT_SIZE
                        }}
                      >
                        Посмотреть на Яндекс.Панорамах
                      </a>

                      {/* ============================================================ */}
                      {/* КНОПКА ПОЛУЧЕНИЯ РЕКОМЕНДАЦИИ ИИ */}
                      {/* ============================================================ */}
                      <button
                        onClick={() => fetchRecommendation(cluster.id)} // При клике — запрос к бэкенду
                        disabled={loadingRecommendation === cluster.id} // Блокируем кнопку во время загрузки
                        style={{
                          display: 'block',
                          width: '100%',
                          padding: '8px 10px',
                          backgroundColor: loadingRecommendation === cluster.id ? '#95a5a6' : '#3498db', // Серый при загрузке, синий в обычном состоянии
                          color: '#fff',
                          border: 'none',
                          borderRadius: '4px',
                          fontWeight: 'bold',
                          textAlign: 'center',
                          boxSizing: 'border-box',
                          cursor: loadingRecommendation === cluster.id ? 'not-allowed' : 'pointer', // Курсор-запрет при загрузке
                          fontSize: FONT_SIZE
                        }}
                      >
                        {loadingRecommendation === cluster.id ? 'Анализ ИИ...' : 'Рекомендации ИИ'}
                      </button>

                                            {/* ============================================================ */}
                      {/* ОТОБРАЖЕНИЕ РЕКОМЕНДАЦИИ ИИ (ПРОКРУЧИВАЕМОЕ ОКНО) */}
                      {/* ============================================================ */}
                      {/* Показываем рекомендацию, если она загружена для этого кластера */}
                      {recommendations[cluster.id] && (
                        <div style={{
                          marginTop: '10px',
                          backgroundColor: '#ebf5fb', // Светло-синий фон (как кнопка, но светлее для читаемости)
                          borderRadius: '4px',
                          border: '1px solid #3498db', // Синяя рамка (как кнопка)
                          overflow: 'hidden' // Скрываем содержимое за рамкой
                        }}>
                          {/* Заголовок окна (не прокручивается) */}
                          <div style={{
                            padding: '8px 10px',
                            backgroundColor: '#3498db', // Синий фон (как кнопка)
                            color: '#fff', // Белый текст
                            fontWeight: 'bold',
                            fontSize: FONT_SIZE,
                            borderBottom: '1px solid #2980b9' // Тёмно-синяя граница снизу
                          }}>
                            Рекомендации ИИ
                          </div>

                          {/* Прокручиваемая область с текстом */}
                          <div style={{
                            maxHeight: '150px', // Максимальная высота окна
                            overflowY: 'auto', // Вертикальная прокрутка при необходимости
                            padding: '10px',
                            fontSize: FONT_SIZE,
                            lineHeight: '1.5',
                            whiteSpace: 'pre-wrap', // Сохраняем переносы строк
                            color: '#2c3e50' // Тёмно-серый текст (для читаемости на светло-синем фоне)
                          }}>
                            {recommendations[cluster.id]}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </Popup>
              </Marker>
            ))
          )}
        </MapContainer>
      </div>

      {/* Панель статистики справа */}
      <StatsPanel />
    </div>
  )
}

export default App