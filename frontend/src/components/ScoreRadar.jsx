import {
  RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  Radar, ResponsiveContainer, Tooltip
} from 'recharts'

const DIMENSIONS = [
  { key: 'hook', label: 'Hook' },
  { key: 'emotion', label: 'Emotion' },
  { key: 'shareability', label: 'Share' },
  { key: 'retention', label: 'Retention' },
  { key: 'controversy', label: 'Debate' },
  { key: 'novelty', label: 'Novelty' },
]

export default function ScoreRadar({ scores, size = 200 }) {
  if (!scores) return null

  const data = DIMENSIONS.map(d => ({
    dimension: d.label,
    score: scores[d.key] || 0,
    fullMark: 10,
  }))

  return (
    <div style={{ width: size, height: size }}>
      <ResponsiveContainer>
        <RadarChart data={data}>
          <PolarGrid stroke="#ffffff10" />
          <PolarAngleAxis
            dataKey="dimension"
            tick={{ fill: '#a0a0b0', fontSize: 11 }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 10]}
            tick={false}
            axisLine={false}
          />
          <Radar
            dataKey="score"
            stroke="#6c5ce7"
            fill="#6c5ce7"
            fillOpacity={0.3}
            strokeWidth={2}
          />
          <Tooltip
            contentStyle={{
              background: '#16213e',
              border: '1px solid #ffffff10',
              borderRadius: 8,
              color: '#fff',
              fontSize: 12,
            }}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}
