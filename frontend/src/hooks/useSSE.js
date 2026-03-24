import { useState, useEffect, useCallback, useRef } from 'react'

export default function useSSE(url) {
  const [stages, setStages] = useState({})
  const [currentStage, setCurrentStage] = useState(null)
  const [isComplete, setIsComplete] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const eventSourceRef = useRef(null)

  const connect = useCallback(() => {
    if (!url) return

    setStages({})
    setCurrentStage(null)
    setIsComplete(false)
    setError(null)
    setResult(null)

    const es = new EventSource(url)
    eventSourceRef.current = es

    es.addEventListener('progress', (e) => {
      const data = JSON.parse(e.data)
      setCurrentStage(data.stage)
      setStages((prev) => ({
        ...prev,
        [data.stage]: {
          stage: data.stage,
          name: data.stage_name,
          progress: data.progress,
          message: data.message,
        },
      }))
    })

    es.addEventListener('complete', (e) => {
      const data = JSON.parse(e.data)
      setResult(data)
      setIsComplete(true)
      es.close()
    })

    es.addEventListener('error', (e) => {
      if (e.data) {
        const data = JSON.parse(e.data)
        setError(data.message)
      } else {
        setError('Connection lost')
      }
      es.close()
    })

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) return
      setError('Connection lost')
      es.close()
    }
  }, [url])

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
    }
  }, [])

  return { stages, currentStage, isComplete, error, result, connect }
}
