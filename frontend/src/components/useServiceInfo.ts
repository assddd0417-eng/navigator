import { useEffect, useState } from 'react'
import { getServiceInfo, type ServiceInfo } from '../api/navigator'

let cached: ServiceInfo | null = null
let pending: Promise<ServiceInfo> | null = null

/** 서비스 안내 정보. 한 번만 불러와 모듈에 보관한다. */
export function useServiceInfo(): ServiceInfo | null {
  const [info, setInfo] = useState<ServiceInfo | null>(cached)
  useEffect(() => {
    if (cached) return
    pending ??= getServiceInfo()
    let live = true
    pending.then((d) => { cached = d; if (live) setInfo(d) }).catch(() => { pending = null })
    return () => { live = false }
  }, [])
  return info
}
