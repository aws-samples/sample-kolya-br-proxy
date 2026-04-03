<template>
  <q-page class="q-pa-md">
    <div class="text-h4 q-mb-md">Playground</div>

    <div class="row q-col-gutter-md">
      <!-- Left Configuration Panel -->
      <div class="col-12 col-md-4">
        <q-card dark bordered class="bg-grey-9" style="height: calc(100vh - 200px); display: flex; flex-direction: column">
          <q-card-section class="q-pa-lg" style="flex: 1; overflow-y: auto">
            <div class="text-h6 q-mb-lg">Configuration</div>

            <q-select
              v-model="selectedToken"
              :options="tokenOptions"
              label="API Key"
              outlined
              rounded
              dark
              class="q-mb-lg"
              emit-value
              map-options
              hint="Select an API Key"
              :loading="tokensStore.loading"
              @update:model-value="onTokenChange"
            />

            <q-select
              v-model="selectedModel"
              :options="modelOptions"
              label="Model"
              outlined
              rounded
              dark
              class="q-mb-lg"
              emit-value
              map-options
              :loading="modelsStore.loading"
            />

            <!-- SDK Protocol selector -->
            <div v-if="sdkOptions.length > 0" class="q-mb-lg">
              <div class="text-caption text-grey-5 q-mb-xs">SDK Protocol</div>
              <q-btn-toggle
                v-model="selectedSdk"
                :options="sdkOptions"
                no-caps
                rounded
                unelevated
                toggle-color="primary"
                color="grey-8"
                text-color="grey-4"
                class="full-width"
                spread
                dense
              />
            </div>

            <q-input
              v-model.number="temperature"
              label="Temperature"
              outlined
              rounded
              dark
              type="number"
              step="0.1"
              min="0"
              max="2"
              class="q-mb-lg"
              input-class="no-spinners"
            />

            <q-input
              v-model.number="maxTokens"
              label="Max Tokens"
              outlined
              rounded
              dark
              type="number"
              class="q-mb-lg"
              input-class="no-spinners"
            />

            <q-btn
              label="Reset"
              color="grey-7"
              @click="clearMessages"
              unelevated
              class="full-width"
            />
          </q-card-section>
        </q-card>
      </div>

      <!-- Right Chat Panel -->
      <div class="col-12 col-md-8">
        <q-card dark bordered class="bg-grey-9 chat-card" style="height: calc(100vh - 200px); display: flex; flex-direction: column">
          <q-card-section ref="chatMessagesRef" class="q-pa-md chat-messages" style="flex: 1; overflow-y: auto; position: relative;" :style="{ backgroundImage: `url(${catImage})` }">
            <div v-if="messages.length === 0" class="text-center text-grey-7 q-mt-xl" style="position: relative; z-index: 1;">
              Start conversation...
            </div>

            <div v-for="(msg, index) in messages" :key="index" class="q-mb-md" style="position: relative; z-index: 1;">
              <div
                :class="[
                  'q-pa-md rounded-borders',
                  msg.role === 'user' ? 'bg-grey-8 text-right' : 'bg-grey-9'
                ]"
              >
                <div class="text-caption text-grey-5 q-mb-xs">
                  {{ msg.role === 'user' ? 'You' : 'Assistant' }}
                  <q-badge v-if="msg.role === 'assistant' && msg.sdk" :label="msg.sdk" color="grey-7" class="q-ml-xs" />
                </div>
                <!-- Loading state -->
                <div v-if="!msg.content && !msg.imageUrls?.length" class="text-grey-6">
                  <q-spinner-dots size="sm" />
                </div>
                <!-- Text content -->
                <div v-if="msg.content" style="white-space: pre-wrap">{{ msg.content }}</div>
                <!-- Image content (Gemini image models return base64 data URLs) -->
                <div v-if="msg.imageUrls?.length" class="q-mt-sm">
                  <img
                    v-for="(imgUrl, imgIdx) in msg.imageUrls"
                    :key="imgIdx"
                    :src="imgUrl"
                    class="generated-image"
                    alt="Generated image"
                  />
                </div>
              </div>
            </div>
            <div ref="messagesEndRef"></div>
          </q-card-section>

          <q-card-section class="q-pa-md bg-grey-10 chat-input">
            <!-- Image upload preview -->
            <div v-if="uploadedImages.length > 0" class="row q-gutter-xs q-mb-sm">
              <div v-for="(img, idx) in uploadedImages" :key="idx" class="upload-preview-wrapper">
                <img :src="`data:${img.mimeType};base64,${img.base64}`" class="upload-preview" />
                <q-btn
                  icon="close"
                  size="xs"
                  round
                  flat
                  color="white"
                  class="upload-preview-remove"
                  @click="uploadedImages.splice(idx, 1)"
                />
              </div>
            </div>
            <!-- Hidden file input -->
            <input
              ref="fileInputRef"
              type="file"
              accept="image/*"
              multiple
              style="display: none"
              @change="onFileSelected"
            />
            <div class="row q-gutter-sm">
              <q-btn
                icon="attach_file"
                color="grey-8"
                round
                unelevated
                @click="fileInputRef?.click()"
                :disable="loading"
              >
                <q-tooltip>Attach image</q-tooltip>
              </q-btn>
              <q-input
                v-model="userMessage"
                outlined
                rounded
                dark
                placeholder="Enter message..."
                class="col"
                @keyup.enter="sendMessage"
                :disable="loading"
              />
              <q-btn
                icon="send"
                color="grey-8"
                round
                unelevated
                @click="sendMessage"
                :loading="loading"
                :disable="!userMessage && uploadedImages.length === 0"
              />
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue';
import { Notify } from 'quasar';
import { useTokensStore } from 'src/stores/tokens';
import { useModelsStore } from 'src/stores/models';
import { getApiBaseUrl } from 'src/utils/api';
import catImage from 'src/assets/kunt-black-kunt.gif';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  imageUrls?: string[];
  sdk?: string;  // which SDK was used for this response
}

const tokensStore = useTokensStore();
const modelsStore = useModelsStore();

const selectedToken = ref<string | null>(null);
const selectedModel = ref<string | null>(null);
const selectedSdk = ref<'openai' | 'anthropic' | 'gemini'>('openai');
const temperature = ref(0.7);
const maxTokens = ref(2048);
const userMessage = ref('');
const messages = ref<Message[]>([]);
const loading = ref(false);
const chatMessagesRef = ref<HTMLElement | null>(null);
const messagesEndRef = ref<HTMLElement | null>(null);
const typewriterQueue = ref<string>('');
const isTyping = ref(false);
const fileInputRef = ref<HTMLInputElement | null>(null);
const uploadedImages = ref<Array<{ base64: string; mimeType: string; name: string }>>([])

// ---------------------------------------------------------------------------
// SDK options based on selected model
// ---------------------------------------------------------------------------

const sdkOptions = computed(() => {
  const model = selectedModel.value || '';
  if (!model) return [];
  // Gemini SDK protocol only works with Gemini models (direct Google API proxy).
  // OpenAI & Anthropic protocols work with all models (routed via Bedrock/Gemini on the backend).
  if (model.includes('gemini')) {
    return [
      { label: 'OpenAI', value: 'openai' },
      { label: 'Anthropic', value: 'anthropic' },
      { label: 'Gemini SDK', value: 'gemini' },
    ];
  }
  return [
    { label: 'OpenAI', value: 'openai' },
    { label: 'Anthropic', value: 'anthropic' },
  ];
});

// Auto-set default SDK when model changes
watch(selectedModel, (newModel) => {
  if (!newModel) return;
  if (newModel.includes('gemini')) {
    selectedSdk.value = 'gemini';
  } else if (newModel.includes('anthropic')) {
    selectedSdk.value = 'anthropic';
  } else {
    selectedSdk.value = 'openai';
  }
});

const tokenOptions = computed(() => {
  return tokensStore.tokens.map(token => ({
    label: token.name,
    value: token.id,
  }));
});

const modelOptions = computed(() => {
  if (!selectedToken.value) {
    return [];
  }
  return modelsStore.models
    .filter(model => model.is_active)
    .map(model => ({
      label: model.friendly_name || model.model_name,
      value: model.model_id,
    }));
});

/** Image generation models don't support streaming */
function isImageModel(modelId: string | null): boolean {
  if (!modelId) return false;
  return modelId.includes('-image') || modelId.includes('canvas') || modelId.includes('imagen');
}

async function onTokenChange() {
  selectedModel.value = null;
  if (selectedToken.value) {
    await modelsStore.fetchModels(selectedToken.value);
  }
}

onMounted(async () => {
  await tokensStore.fetchTokens();
});

async function scrollToBottom() {
  await nextTick();
  if (messagesEndRef.value) {
    messagesEndRef.value.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }
}

function startTypewriter(assistantMsgIndex: number) {
  if (isTyping.value || !typewriterQueue.value) return;

  isTyping.value = true;
  const interval = setInterval(() => {
    if (typewriterQueue.value.length === 0) {
      clearInterval(interval);
      isTyping.value = false;
      return;
    }

    const chunkSize = Math.floor(Math.random() * 3) + 1;
    const chunk = typewriterQueue.value.slice(0, chunkSize);
    typewriterQueue.value = typewriterQueue.value.slice(chunkSize);

    const currentMsg = messages.value[assistantMsgIndex];
    if (currentMsg) {
      currentMsg.content += chunk;
      messages.value = [...messages.value];
      void scrollToBottom();
    }
  }, 30);
}

function clearMessages() {
  messages.value = [];
  userMessage.value = '';
  typewriterQueue.value = '';
  isTyping.value = false;
  selectedToken.value = null;
  selectedModel.value = null;
  temperature.value = 0.7;
  maxTokens.value = 2048;
  uploadedImages.value = [];
}

// ---------------------------------------------------------------------------
// Image upload handling
// ---------------------------------------------------------------------------

function onFileSelected(event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.files?.length) return;

  for (const file of Array.from(input.files)) {
    if (!file.type.startsWith('image/')) continue;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      // dataUrl format: "data:image/png;base64,iVBOR..."
      const base64 = dataUrl.split(',')[1] || '';
      uploadedImages.value.push({
        base64,
        mimeType: file.type,
        name: file.name,
      });
    };
    reader.readAsDataURL(file);
  }

  // Reset input so the same file can be selected again
  input.value = '';
}

// ---------------------------------------------------------------------------
// Get actual token value
// ---------------------------------------------------------------------------

async function getPlainToken(): Promise<string> {
  const apiBaseUrl = getApiBaseUrl();
  const response = await fetch(`${apiBaseUrl}/admin/tokens/${selectedToken.value}/plain`, {
    headers: {
      'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
      'Cache-Control': 'no-cache',
    },
  });
  if (!response.ok) throw new Error('Unable to get API Key');
  const tokenData = await response.json();
  return tokenData.token;
}

// ---------------------------------------------------------------------------
// Build conversation history (excluding last empty assistant placeholder)
// ---------------------------------------------------------------------------

function getConversationHistory(): Array<{ role: string; content: string }> {
  return messages.value
    .slice(0, -1) // exclude assistant placeholder
    .filter(m => m.content && m.content.trim())
    .map(m => ({ role: m.role, content: m.content }));
}

/** Build OpenAI-format messages with image_url support */
function getOpenAIMessages(): Array<{ role: string; content: string | Array<Record<string, unknown>> }> {
  return messages.value
    .slice(0, -1)
    .filter(m => m.content?.trim() || m.imageUrls?.length)
    .map(m => {
      if (m.imageUrls?.length && m.role === 'user') {
        const parts: Array<Record<string, unknown>> = [];
        for (const url of m.imageUrls) {
          parts.push({ type: 'image_url', image_url: { url } });
        }
        if (m.content?.trim()) {
          parts.push({ type: 'text', text: m.content });
        }
        return { role: m.role, content: parts };
      }
      return { role: m.role, content: m.content };
    });
}

/** Build Anthropic-format messages with image source support */
function getAnthropicMessages(): Array<{ role: string; content: string | Array<Record<string, unknown>> }> {
  return messages.value
    .slice(0, -1)
    .filter(m => m.content?.trim() || m.imageUrls?.length)
    .map(m => {
      if (m.imageUrls?.length && m.role === 'user') {
        const parts: Array<Record<string, unknown>> = [];
        for (const url of m.imageUrls) {
          // Extract base64 and media_type from data URL
          const match = url.match(/^data:([^;]+);base64,(.+)$/);
          if (match) {
            parts.push({
              type: 'image',
              source: { type: 'base64', media_type: match[1], data: match[2] },
            });
          }
        }
        if (m.content?.trim()) {
          parts.push({ type: 'text', text: m.content });
        }
        return { role: m.role, content: parts };
      }
      return { role: m.role, content: m.content };
    });
}

// ---------------------------------------------------------------------------
// Send via OpenAI Compatible (/v1/chat/completions)
// ---------------------------------------------------------------------------

async function sendViaOpenAI(plainToken: string, assistantMsgIndex: number) {
  const apiBaseUrl = getApiBaseUrl();
  const useStream = !isImageModel(selectedModel.value);

  const chatResponse = await fetch(`${apiBaseUrl}/v1/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${plainToken}`,
      'Cache-Control': 'no-cache',
    },
    body: JSON.stringify({
      model: selectedModel.value,
      messages: getOpenAIMessages(),
      stream: useStream,
      ...(temperature.value !== null && { temperature: temperature.value }),
      ...(maxTokens.value !== null && { max_tokens: maxTokens.value }),
    }),
  });

  if (!chatResponse.ok) {
    const error = await chatResponse.json().catch(() => ({}));
    throw new Error((error as Record<string, string>).detail || chatResponse.statusText || `HTTP ${chatResponse.status}`);
  }

  if (!useStream) {
    loading.value = false;
    const responseData = await chatResponse.json() as Record<string, unknown>;
    const choices = responseData.choices as Array<Record<string, unknown>> | undefined;
    const content = choices?.[0]?.message
      ? (choices[0].message as Record<string, unknown>).content
      : undefined;
    if (typeof content === 'string') {
      typewriterQueue.value = content;
      startTypewriter(assistantMsgIndex);
    }
    return;
  }

  const reader = chatResponse.body?.getReader();
  if (!reader) throw new Error('Unable to read response stream');

  loading.value = false;
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    for (const line of chunk.split('\n')) {
      if (!line.startsWith('data: ') || line.slice(6) === '[DONE]') continue;
      try {
        const parsed = JSON.parse(line.slice(6)) as Record<string, unknown>;
        const choices = parsed.choices as Array<Record<string, unknown>> | undefined;
        const delta = choices?.[0]?.delta as Record<string, unknown> | undefined;
        if (typeof delta?.content === 'string' && delta.content) {
          typewriterQueue.value += delta.content;
          if (!isTyping.value) startTypewriter(assistantMsgIndex);
        }
      } catch { /* ignore parse errors */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Send via Anthropic (/v1/messages)
// ---------------------------------------------------------------------------

async function sendViaAnthropic(plainToken: string, assistantMsgIndex: number) {
  const apiBaseUrl = getApiBaseUrl();

  const chatResponse = await fetch(`${apiBaseUrl}/v1/messages`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': plainToken,
      'X-Requested-With': 'XMLHttpRequest',
      'Cache-Control': 'no-cache',
    },
    body: JSON.stringify({
      model: selectedModel.value,
      messages: getAnthropicMessages(),
      stream: true,
      max_tokens: maxTokens.value || 2048,
      ...(temperature.value !== null && { temperature: temperature.value }),
    }),
  });

  if (!chatResponse.ok) {
    const error = await chatResponse.json().catch(() => ({}));
    throw new Error((error as Record<string, string>).detail || chatResponse.statusText || `HTTP ${chatResponse.status}`);
  }

  const reader = chatResponse.body?.getReader();
  if (!reader) throw new Error('Unable to read response stream');

  loading.value = false;
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || ''; // keep incomplete line in buffer

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const parsed = JSON.parse(line.slice(6)) as Record<string, unknown>;
        // Anthropic SSE: content_block_delta with text_delta
        if (parsed.type === 'content_block_delta') {
          const delta = parsed.delta as Record<string, unknown> | undefined;
          if (delta?.type === 'text_delta' && typeof delta.text === 'string') {
            typewriterQueue.value += delta.text;
            if (!isTyping.value) startTypewriter(assistantMsgIndex);
          }
        }
      } catch { /* ignore parse errors */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Send via Gemini SDK (/v1beta/models/{model}:streamGenerateContent)
// ---------------------------------------------------------------------------

async function sendViaGemini(plainToken: string, assistantMsgIndex: number) {
  const apiBaseUrl = getApiBaseUrl();
  const model = selectedModel.value || '';

  // Convert conversation to Gemini format
  const history = getConversationHistory();
  const contents: Array<{ role: string; parts: Array<Record<string, unknown>> }> = history.map(m => ({
    role: m.role === 'assistant' ? 'model' : 'user',
    parts: [{ text: m.content }] as Array<Record<string, unknown>>,
  }));

  // Build parts for the latest user message (last entry in contents)
  // Include uploaded images as inlineData
  if (uploadedImages.value.length > 0 && contents.length > 0) {
    const lastContent = contents[contents.length - 1]!;
    const newParts: Array<Record<string, unknown>> = [];
    // Add images first
    for (const img of uploadedImages.value) {
      newParts.push({ inlineData: { mimeType: img.mimeType, data: img.base64 } });
    }
    // Add existing text parts
    newParts.push(...lastContent.parts);
    lastContent.parts = newParts;
  }

  const body: Record<string, unknown> = { contents };
  const genConfig: Record<string, unknown> = {};
  if (temperature.value !== null) genConfig.temperature = temperature.value;
  if (maxTokens.value !== null) genConfig.maxOutputTokens = maxTokens.value;
  if (Object.keys(genConfig).length) body.generationConfig = genConfig;

  const url = `${apiBaseUrl}/v1beta/models/${model}:streamGenerateContent?alt=sse&key=${plainToken}`;

  const chatResponse = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest',
      'Cache-Control': 'no-cache',
    },
    body: JSON.stringify(body),
  });

  if (!chatResponse.ok) {
    const error = await chatResponse.json().catch(() => ({}));
    throw new Error((error as Record<string, string>).detail || (error as Record<string, Record<string, string>>).error?.message || chatResponse.statusText || `HTTP ${chatResponse.status}`);
  }

  const reader = chatResponse.body?.getReader();
  if (!reader) throw new Error('Unable to read response stream');

  loading.value = false;
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      try {
        const parsed = JSON.parse(line.slice(6)) as Record<string, unknown>;
        // Gemini SSE: candidates[0].content.parts[].text or .inlineData
        const candidates = parsed.candidates as Array<Record<string, unknown>> | undefined;
        if (!candidates?.length) continue;
        const firstCandidate = candidates[0];
        if (!firstCandidate) continue;
        const content = firstCandidate.content as Record<string, unknown> | undefined;
        const parts = content?.parts as Array<Record<string, unknown>> | undefined;
        if (!parts?.length) continue;
        for (const part of parts) {
          // Text content
          if (typeof part.text === 'string' && part.text) {
            typewriterQueue.value += part.text;
            if (!isTyping.value) startTypewriter(assistantMsgIndex);
          }
          // Image content (inlineData from Gemini image generation)
          const inlineData = part.inlineData as Record<string, string> | undefined;
          if (inlineData?.mimeType && inlineData?.data) {
            const dataUrl = `data:${inlineData.mimeType};base64,${inlineData.data}`;
            const currentMsg = messages.value[assistantMsgIndex];
            if (currentMsg) {
              if (!currentMsg.imageUrls) currentMsg.imageUrls = [];
              currentMsg.imageUrls.push(dataUrl);
              messages.value = [...messages.value];
              void scrollToBottom();
            }
          }
        }
      } catch { /* ignore parse errors */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Main send function — dispatches to the correct SDK path
// ---------------------------------------------------------------------------

async function sendMessage() {
  const hasText = userMessage.value.trim().length > 0;
  const hasImages = uploadedImages.value.length > 0;
  if (!hasText && !hasImages) return;

  if (!selectedToken.value) {
    Notify.create({ type: 'warning', message: 'Please select API Key first', position: 'top' });
    return;
  }
  if (!selectedModel.value) {
    Notify.create({ type: 'warning', message: 'Please select model first', position: 'top' });
    return;
  }

  // Build user message with optional image previews
  const userImageUrls = uploadedImages.value.map(img => `data:${img.mimeType};base64,${img.base64}`);
  const userMsg: Message = {
    role: 'user',
    content: userMessage.value,
    ...(userImageUrls.length > 0 && { imageUrls: userImageUrls }),
  };
  messages.value.push(userMsg);
  const currentMessage = userMessage.value;
  const currentImages = [...uploadedImages.value];
  userMessage.value = '';
  loading.value = true;
  void scrollToBottom();

  // Create assistant placeholder
  const assistantMsgIndex = messages.value.length;
  messages.value.push({ role: 'assistant', content: '', sdk: selectedSdk.value });
  void scrollToBottom();

  try {
    const plainToken = await getPlainToken();

    switch (selectedSdk.value) {
      case 'anthropic':
        await sendViaAnthropic(plainToken, assistantMsgIndex);
        break;
      case 'gemini':
        await sendViaGemini(plainToken, assistantMsgIndex);
        break;
      case 'openai':
      default:
        await sendViaOpenAI(plainToken, assistantMsgIndex);
        break;
    }
    // Clear uploaded images on success
    uploadedImages.value = [];
  } catch (error) {
    Notify.create({
      type: 'negative',
      message: 'Send failed: ' + (error instanceof Error ? error.message : 'Unknown error'),
      position: 'top',
    });
    messages.value = messages.value.slice(0, -2);
    userMessage.value = currentMessage;
    uploadedImages.value = currentImages;
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped lang="scss">
.rounded-borders {
  border-radius: 12px;
}

.chat-messages {
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  background-attachment: local;
}

.generated-image {
  max-width: 100%;
  max-height: 600px;
  border-radius: 8px;
  display: block;
  margin-top: 8px;
}

.upload-preview-wrapper {
  position: relative;
  display: inline-block;
}

.upload-preview {
  width: 60px;
  height: 60px;
  object-fit: cover;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.upload-preview-remove {
  position: absolute;
  top: -6px;
  right: -6px;
  background: rgba(0, 0, 0, 0.7) !important;
  width: 20px;
  height: 20px;
}

:deep(.no-spinners) {
  appearance: textfield;
  -moz-appearance: textfield;

  &::-webkit-outer-spin-button,
  &::-webkit-inner-spin-button {
    appearance: none;
    -webkit-appearance: none;
    margin: 0;
  }
}
</style>
