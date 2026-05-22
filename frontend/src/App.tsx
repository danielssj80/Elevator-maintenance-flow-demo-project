import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import ElevatorDetail from './pages/ElevatorDetail'
import PostVisitReport from './pages/PostVisitReport'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/elevators/:id" element={<ElevatorDetail />} />
        <Route path="/elevators/:id/report" element={<PostVisitReport />} />
      </Routes>
    </BrowserRouter>
  )
}
