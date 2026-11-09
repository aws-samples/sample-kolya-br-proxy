export function extractErrorMessage(
  error: unknown,
  fallback = 'Operation failed',
): string {
  if (error && typeof error === 'object' && 'response' in error) {
    const data = (
      error as {
        response?: { data?: { detail?: unknown; error?: { message?: unknown } } };
      }
    ).response?.data;
    // Backend envelope is {"error": {"message"}}; FastAPI default is {"detail"}.
    const message = data?.error?.message ?? data?.detail;
    if (typeof message === 'string' && message) return message;
  }
  return fallback;
}
