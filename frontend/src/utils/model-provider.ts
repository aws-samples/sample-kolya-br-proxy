const PROVIDER_NAMES: Record<string, string> = {
  ai21: 'AI21',
  amazon: 'Amazon',
  anthropic: 'Anthropic',
  cohere: 'Cohere',
  deepseek: 'DeepSeek',
  google: 'Google',
  luma: 'Luma',
  meta: 'Meta',
  minimax: 'MiniMax',
  mistral: 'Mistral',
  moonshot: 'Moonshot',
  nvidia: 'NVIDIA',
  openai: 'OpenAI',
  qwen: 'Qwen',
  stability: 'Stability',
  twelvelabs: 'TwelveLabs',
  writer: 'Writer',
  xai: 'xAI',
  zai: 'ZAI',
};

// Keep this aligned with BedrockClient.INFERENCE_PROFILE_PREFIXES.
const CROSS_REGION_PREFIX = /^(global|us|eu|apac|au|ca|jp)\./;

/** Extract a human-readable provider from a model or inference-profile ID. */
export function getModelProvider(modelId: string): string {
  const stripped = modelId.replace(CROSS_REGION_PREFIX, '');
  const prefix = (stripped.split('.')[0] ?? '').toLowerCase();

  const knownProvider = PROVIDER_NAMES[prefix];
  if (knownProvider) return knownProvider;

  if (modelId.startsWith('gemini-') || modelId.startsWith('gemini/')) {
    return 'Gemini';
  }

  return prefix.charAt(0).toUpperCase() + prefix.slice(1);
}
