import ReactPlayer from 'react-player'

export default function VideoPreview({ url, light = false }) {
  if (!url) return null

  return (
    <div className="rounded-xl overflow-hidden bg-black aspect-video">
      <ReactPlayer
        url={url}
        controls
        width="100%"
        height="100%"
        light={light}
        config={{
          file: {
            attributes: { controlsList: 'nodownload' },
          },
        }}
      />
    </div>
  )
}
