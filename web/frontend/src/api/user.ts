import request from './request'

export interface UserInfo {
  id: number
  name: string
  email?: string
}

export function getUser() {
  return request<UserInfo>({
    url: '/user',
    method: 'get',
  })
}
