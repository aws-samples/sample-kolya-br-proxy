<template>
  <div class="block-text" :class="v.cls"><template v-if="v.tool"><span class="tool-name">{{ v.name }}</span>{{ ' ' }}<span class="tool-id">{{ v.id }}</span><div class="tool-input">{{ v.text }}</div></template><template v-else>{{ v.text }}</template></div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { blockView, type ContentBlock } from '@/utils/traceBlocks';

const props = defineProps<{ block: ContentBlock }>();
const v = computed(() => blockView(props.block));
</script>
