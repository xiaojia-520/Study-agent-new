import axios from 'axios'

import { defaultBackendBaseUrl } from './studyAgent'

const request = axios.create({
  baseURL: defaultBackendBaseUrl,
  timeout: 5000,
})

export default request
