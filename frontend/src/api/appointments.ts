import api from './client'

export type AppointmentStatus = 'REQUESTED' | 'CONFIRMED' | 'DECLINED' | 'CANCELLED' | 'COMPLETED' | 'NO_SHOW'

export interface Appointment {
  id: string
  student_id: string
  counsellor_id: string
  title: string
  start_at: string
  end_at: string
  timezone: string
  mode: string
  location?: string | null
  notes?: string | null
  status: AppointmentStatus
  cancellation_reason?: string | null
  student_name?: string
  counsellor_name?: string
}

export async function getAppointments(status?: AppointmentStatus): Promise<Appointment[]> {
  const { data } = await api.get('/appointments', { params: status ? { status } : undefined })
  return data
}

export async function createAppointment(payload: {
  student_id: string
  title: string
  start_at: string
  end_at: string
  timezone?: string
  mode?: string
  location?: string
  notes?: string
}): Promise<Appointment> {
  const { data } = await api.post('/appointments', payload)
  return data
}

export async function updateAppointmentStatus(id: string, status: AppointmentStatus, reason?: string): Promise<Appointment> {
  const { data } = await api.patch(`/appointments/${id}/status`, { status, reason })
  return data
}
