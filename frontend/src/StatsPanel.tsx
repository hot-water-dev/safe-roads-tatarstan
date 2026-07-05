import { useEffect, useState } from 'react'
import axios from 'axios'

// Единый размер шрифта для всего приложения
const FONT_SIZE = '12px'

// Интерфейсы для данных статистики
interface District {
  district: string
  cnt: number
  killed: number
  injured: number
}

interface DtpType {
  dtp_type: string
  cnt: number
  killed: number
}

interface Monthly {
  month: string
  cnt: number
  killed: number
}

interface Stats {
  total_accidents: number
  total_killed: number
  total_injured: number
  top_districts: District[]
  top_types: DtpType[]
  monthly: Monthly[]
}

function StatsPanel() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    axios.get('http://localhost:8000/api/stats')
      .then(response => {
        setStats(response.data)
        setLoading(false)
      })
      .catch(error => {
        console.error('Ошибка загрузки статистики:', error)
        setLoading(false)
      })
  }, [])

  if (loading) {
    return (
      <div style={styles.panel}>
        <div style={styles.loading}>Загрузка статистики...</div>
      </div>
    )
  }

  if (!stats) {
    return (
      <div style={styles.panel}>
        <div style={styles.error}>Не удалось загрузить статистику</div>
      </div>
    )
  }

  return (
    <div style={styles.panel}>
      {/* Общая статистика */}
      <div style={styles.section}>
        <h2 style={styles.title}>Общая статистика</h2>
        <div style={styles.statsGrid}>
          <div style={styles.statCard}>
            <div style={styles.statNumber}>{stats.total_accidents}</div>
            <div style={styles.statLabel}>Всего ДТП</div>
          </div>
          <div style={styles.statCard}>
            <div style={{ ...styles.statNumber, color: '#e74c3c' }}>{stats.total_killed}</div>
            <div style={styles.statLabel}>Погибло</div>
          </div>
          <div style={styles.statCard}>
            <div style={styles.statNumber}>{stats.total_injured}</div>
            <div style={styles.statLabel}>Ранено</div>
          </div>
        </div>
      </div>

      {/* Топ районов */}
      <div style={styles.section}>
        <h2 style={styles.title}>Топ-10 районов</h2>
        <div style={styles.list}>
          {stats.top_districts.map((d, index) => (
            <div key={index} style={styles.listItem}>
              <span style={styles.rank}>{index + 1}.</span>
              <span style={styles.name}>{d.district}</span>
              <span style={styles.count}>
                {d.cnt}
                {d.killed > 0 && <span style={styles.killed}> ({d.killed})</span>}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Топ типов ДТП */}
      <div style={styles.section}>
        <h2 style={styles.title}>Топ-10 типов ДТП</h2>
        <div style={styles.list}>
          {stats.top_types.map((t, index) => (
            <div key={index} style={styles.listItem}>
              <span style={styles.rank}>{index + 1}.</span>
              <span style={styles.name}>{t.dtp_type}</span>
              <span style={styles.count}>
                {t.cnt}
                {t.killed > 0 && <span style={styles.killed}> ({t.killed})</span>}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Динамика по месяцам */}
      <div style={styles.section}>
        <h2 style={styles.title}>Динамика по месяцам</h2>
        <div style={styles.list}>
          {[...stats.monthly]
            .sort((a, b) => {
              const [monthA, yearA] = a.month.split('.').map(Number)
              const [monthB, yearB] = b.month.split('.').map(Number)
              const valueA = yearA * 12 + monthA
              const valueB = yearB * 12 + monthB
              return valueB - valueA
            })
            .map((m, index) => (
              <div key={index} style={styles.listItem}>
                <span style={styles.rank}>{m.month}</span>
                <span style={styles.count}>
                  {m.cnt} ДТП
                  {m.killed > 0 && <span style={styles.killed}> ({m.killed})</span>}
                </span>
              </div>
            ))}
        </div>
      </div>
    </div>
  )
}

// Стили
const styles: { [key: string]: React.CSSProperties } = {
  panel: {
    width: '175px',
    height: '100vh',
    backgroundColor: '#f8f9fa',
    overflowY: 'auto',
    padding: '10px',
    borderLeft: '2px solid #dee2e6',
    fontFamily: 'Arial, sans-serif',
    fontSize: FONT_SIZE // Единый размер шрифта
  },
  loading: {
    textAlign: 'center',
    padding: '20px',
    color: '#6c757d',
  },
  error: {
    textAlign: 'center',
    padding: '20px',
    color: '#dc3545',
  },
  section: {
    marginBottom: '20px',
  },
  title: {
    fontWeight: 'bold',
    marginBottom: '10px',
    color: '#000',
    borderBottom: '1px solid #000',
    paddingBottom: '5px',
    fontSize: FONT_SIZE // Единый размер шрифта
  },
  statsGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr',
    gap: '5px',
  },
  statCard: {
    backgroundColor: 'white',
    padding: '8px',
    borderRadius: '4px',
    textAlign: 'center',
    boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
  },
  statNumber: {
    fontWeight: 'bold',
    color: '#000',
    fontSize: FONT_SIZE // Единый размер шрифта
  },
  statLabel: {
    color: '#7f8c8d',
    marginTop: '3px',
    fontSize: FONT_SIZE // Единый размер шрифта
  },
  list: {
    backgroundColor: 'white',
    borderRadius: '4px',
    padding: '5px',
    boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
  },
  listItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '4px 0',
    borderBottom: '1px solid #000',
    fontSize: FONT_SIZE // Единый размер шрифта
  },
  rank: {
    fontWeight: 'bold',
    color: '#000',
    minWidth: '20px',
  },
  name: {
    flex: 1,
    marginLeft: '5px',
    color: '#000',
  },
  count: {
    color: '#000',
  },
  killed: {
    color: '#e74c3c',
    fontWeight: 'bold',
  },
}

export default StatsPanel