// API Configuration for dual mode support
export const API_CONFIGS = {
  temporal: {
    name: 'Temporal API',
    baseUrl: 'http://127.0.0.1:8000',
    description: 'Uses Temporal workflows for orchestration'
  },
  basic: {
    name: 'Basic API', 
    baseUrl: 'http://127.0.0.1:8001',
    description: 'Direct OpenAI Agents SDK with DB2 persistence'
  }
};

// Default API mode - can be overridden by environment variable
export const DEFAULT_API_MODE = process.env.REACT_APP_API_MODE || 'temporal';

// Get current API configuration
export const getApiConfig = (mode = DEFAULT_API_MODE) => {
  return API_CONFIGS[mode] || API_CONFIGS.temporal;
};

// Legacy export for backward compatibility
export const API_BASE_URL = getApiConfig().baseUrl;
