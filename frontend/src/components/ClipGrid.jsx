import ClipCard from './ClipCard'

export default function ClipGrid({ clips, onPlay, onExport, onEdit }) {
  if (!clips?.length) {
    return (
      <div className="text-center py-12 text-muted">
        <p>No clips generated yet.</p>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {clips.map((clip) => (
        <ClipCard
          key={clip.id}
          clip={clip}
          onPlay={onPlay}
          onExport={onExport}
          onEdit={onEdit}
        />
      ))}
    </div>
  )
}
