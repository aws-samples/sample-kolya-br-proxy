/**
 * Get the API base URL at runtime
 * Checks for runtime config, then falls back to environment variables
 */
export function getApiBaseUrl(): string {
  // Check if there's a runtime config injected by nginx
  const config = (window as unknown as Record<string, Record<string, string>>).__CONFIG__;
  if (config?.apiBaseUrl) {
    return config.apiBaseUrl;
  }

  // Fall back to environment variable
  const envUrl = import.meta.env.VITE_API_BASE_URL;
  if (envUrl) {
    return envUrl;
  }

  // Default fallback
  return 'http://localhost:8000';
}
