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
            <div class="row q-gutter-sm">
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
                :disable="!userMessage"
              />
            </div>
          </q-card-section>
        </q-card>
      </div>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue';
import { Notify } from 'quasar';
import { useTokensStore } from 'src/stores/tokens';
import { useModelsStore } from 'src/stores/models';
import { getApiBaseUrl } from 'src/utils/api';
import catImage from 'src/assets/kunt-black-kunt.gif';

interface Message {
  role: 'user' | 'assistant';
  content: string;
  imageUrls?: string[];  // base64 data URLs from image generation models
}

const tokensStore = useTokensStore();
const modelsStore = useModelsStore();

const selectedToken = ref<string | null>(null);
const selectedModel = ref<string | null>(null);
const temperature = ref(0.7);
const maxTokens = ref(2048);
const userMessage = ref('');
const messages = ref<Message[]>([]);
const loading = ref(false);
const chatMessagesRef = ref<HTMLElement | null>(null);
const messagesEndRef = ref<HTMLElement | null>(null);
const typewriterQueue = ref<string>('');
const isTyping = ref(false);

const tokenOptions = computed(() => {
  return tokensStore.tokens.map(token => ({
    label: token.name,
    value: token.id,
  }));
});

const modelOptions = computed(() => {
  // 如果没有选择 token，返回空列表
  if (!selectedToken.value) {
    return [];
  }

  // 从 modelsStore 获取该 token 的模型列表
  return modelsStore.models
    .filter(model => model.is_active)
    .map(model => ({
      label: model.friendly_name || model.model_name,
      value: model.model_id,  // 使用完整的 model_id (包含 global. 前缀)
    }));
});

/** Image generation models don't support streaming */
function isImageModel(modelId: string | null): boolean {
  if (!modelId) return false;
  return modelId.includes('-image') || modelId.includes('canvas') || modelId.includes('imagen');
}

/** Extract text + image URLs from a non-streaming OpenAI-format response */
function parseNonStreamResponse(data: Record<string, unknown>): { text: string; imageUrls: string[] } {
  const text: string[] = [];
  const imageUrls: string[] = [];

  const choices = data.choices as Array<Record<string, unknown>> | undefined;
  const content = choices?.[0]?.message
    ? (choices[0].message as Record<string, unknown>).content
    : undefined;

  if (typeof content === 'string') {
    text.push(content);
  } else if (Array.isArray(content)) {
    for (const part of content as Array<Record<string, unknown>>) {
      if (part.type === 'text' && typeof part.text === 'string') {
        text.push(part.text);
      } else if (part.type === 'image_url') {
        const url = (part.image_url as Record<string, string> | undefined)?.url;
        if (url) imageUrls.push(url);
      }
    }
  }

  return { text: text.join(''), imageUrls };
}

async function onTokenChange() {
  // 清空当前选择的模型
  selectedModel.value = null;

  // 如果选择了 token，加载该 token 的模型列表
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

// 打字机效果
function startTypewriter(assistantMsgIndex: number) {
  if (isTyping.value || !typewriterQueue.value) return;

  isTyping.value = true;
  const interval = setInterval(() => {
    if (typewriterQueue.value.length === 0) {
      clearInterval(interval);
      isTyping.value = false;
      return;
    }

    // 每次取出 1-3 个字符（模拟打字速度变化）
    const chunkSize = Math.floor(Math.random() * 3) + 1;
    const chunk = typewriterQueue.value.slice(0, chunkSize);
    typewriterQueue.value = typewriterQueue.value.slice(chunkSize);

    const currentMsg = messages.value[assistantMsgIndex];
    if (currentMsg) {
      currentMsg.content += chunk;
      messages.value = [...messages.value];
      void scrollToBottom();
    }
  }, 30); // 每 30ms 显示一批字符
}

function clearMessages() {
  // Clear chat messages
  messages.value = [];
  userMessage.value = '';
  typewriterQueue.value = '';
  isTyping.value = false;

  // Reset configuration
  selectedToken.value = null;
  selectedModel.value = null;
  temperature.value = 0.7;
  maxTokens.value = 2048;
}

async function sendMessage() {
  if (!userMessage.value.trim()) return;

  // Check configuration
  if (!selectedToken.value) {
    Notify.create({
      type: 'warning',
      message: 'Please select API Key first',
      position: 'top',
    });
    return;
  }

  if (!selectedModel.value) {
    Notify.create({
      type: 'warning',
      message: 'Please select model first',
      position: 'top',
    });
    return;
  }

  const userMsg: Message = {
    role: 'user',
    content: userMessage.value,
  };

  messages.value.push(userMsg);
  const currentMessage = userMessage.value;
  userMessage.value = '';
  loading.value = true;

  // Scroll to bottom to show user message
  void scrollToBottom();

  // Create assistant message placeholder immediately
  const assistantMsgIndex = messages.value.length;
  messages.value.push({
    role: 'assistant',
    content: '',
  });
  void scrollToBottom();

  try {
    const apiBaseUrl = getApiBaseUrl();

    // Get actual key of selected token
    const response = await fetch(`${apiBaseUrl}/admin/tokens/${selectedToken.value}/plain`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        'Cache-Control': 'no-cache',
      },
    });

    if (!response.ok) {
      throw new Error('Unable to get API Key');
    }

    const tokenData = await response.json();

    const useStream = !isImageModel(selectedModel.value);

    // Call API
    const chatResponse = await fetch(`${apiBaseUrl}/v1/chat/completions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${tokenData.token}`,
        'Cache-Control': 'no-cache',
      },
      body: JSON.stringify({
        model: selectedModel.value,
        messages: messages.value.slice(0, -1)
          .filter(m => m.content && m.content.trim())
          .map(m => ({
            role: m.role,
            content: m.content,
          })),
        stream: useStream,
        ...(temperature.value !== null && { temperature: temperature.value }),
        ...(maxTokens.value !== null && { max_tokens: maxTokens.value }),
      }),
    });

    if (!chatResponse.ok) {
      let errorMessage = 'Request failed';
      try {
        const error = await chatResponse.json();
        errorMessage = error.detail || error.message || errorMessage;
      } catch {
        errorMessage = chatResponse.statusText || `HTTP ${chatResponse.status}`;
      }
      throw new Error(errorMessage);
    }

    // --- Non-streaming path (image models) ---
    if (!useStream) {
      loading.value = false;
      const responseData = await chatResponse.json() as Record<string, unknown>;
      const { text, imageUrls } = parseNonStreamResponse(responseData);
      const msg = messages.value[assistantMsgIndex];
      if (msg) {
        if (text) {
          typewriterQueue.value = text;
          startTypewriter(assistantMsgIndex);
        }
        if (imageUrls.length) {
          msg.imageUrls = imageUrls;
          messages.value = [...messages.value];
          void scrollToBottom();
        }
      }
      return;
    }

    // --- Streaming path (text/chat models) ---
    const reader = chatResponse.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('Unable to read response stream');
    }

    loading.value = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') continue;

          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            const choices = parsed.choices as Array<Record<string, unknown>> | undefined;
            const delta = choices?.[0]?.delta as Record<string, unknown> | undefined;
            if (!delta) continue;

            // Text content (string)
            if (typeof delta.content === 'string' && delta.content) {
              typewriterQueue.value += delta.content;
              if (!isTyping.value) startTypewriter(assistantMsgIndex);
            }

            // Array content parts
            if (Array.isArray(delta.content)) {
              for (const part of delta.content as Array<Record<string, unknown>>) {
                if (part.type === 'text' && typeof part.text === 'string') {
                  typewriterQueue.value += part.text;
                  if (!isTyping.value) startTypewriter(assistantMsgIndex);
                } else if (part.type === 'image_url') {
                  const url = (part.image_url as Record<string, string> | undefined)?.url;
                  if (url) {
                    const msg = messages.value[assistantMsgIndex];
                    if (msg) {
                      if (!msg.imageUrls) msg.imageUrls = [];
                      msg.imageUrls.push(url);
                      messages.value = [...messages.value];
                      void scrollToBottom();
                    }
                  }
                }
              }
            }
          } catch {
            // Ignore parsing errors
          }
        }
      }
    }
  } catch (error) {
    Notify.create({
      type: 'negative',
      message: 'Send failed: ' + (error instanceof Error ? error.message : 'Unknown error'),
      position: 'top',
    });

    // Remove last two messages (user message and empty assistant message)
    messages.value = messages.value.slice(0, -2);
    userMessage.value = currentMessage;
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
