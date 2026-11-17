import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { loadFitLevels } from './pages/navigator/components'
import './styles.css'

void loadFitLevels().finally(() => createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
))
