<script setup lang="ts">
import { computed } from 'vue'
import DOMPurify from 'dompurify'
import katex from 'katex'
import MarkdownIt from 'markdown-it'
import texmath from 'markdown-it-texmath'

import 'katex/dist/katex.min.css'

const props = defineProps<{
  text: string
}>()

const markdown = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: false,
})
  .enable(['table', 'strikethrough'])
  .use(texmath, {
    engine: katex,
    delimiters: 'brackets',
    katexOptions: {
      throwOnError: false,
      strict: false,
    },
  })

const renderedHtml = computed(() =>
  DOMPurify.sanitize(markdown.render(props.text || ''), {
    USE_PROFILES: { html: true },
  }),
)
</script>

<template>
  <div class="rich-markdown" v-html="renderedHtml" />
</template>

<style scoped>
.rich-markdown {
  overflow-wrap: anywhere;
}

.rich-markdown :deep(*) {
  letter-spacing: 0;
}

.rich-markdown :deep(h1),
.rich-markdown :deep(h2),
.rich-markdown :deep(h3) {
  margin: 0.85rem 0 0.45rem;
  font-weight: 700;
  line-height: 1.35;
}

.rich-markdown :deep(h1) {
  font-size: 1.08rem;
}

.rich-markdown :deep(h2) {
  font-size: 1rem;
}

.rich-markdown :deep(h3) {
  font-size: 0.95rem;
}

.rich-markdown :deep(p),
.rich-markdown :deep(ul),
.rich-markdown :deep(ol),
.rich-markdown :deep(blockquote),
.rich-markdown :deep(table) {
  margin: 0.55rem 0;
}

.rich-markdown :deep(ul),
.rich-markdown :deep(ol) {
  padding-left: 1.25rem;
}

.rich-markdown :deep(li + li) {
  margin-top: 0.2rem;
}

.rich-markdown :deep(blockquote) {
  border-left: 3px solid rgba(var(--accent), 0.35);
  padding-left: 0.85rem;
  color: rgb(var(--text-subtle));
}

.rich-markdown :deep(table) {
  display: block;
  width: 100%;
  overflow-x: auto;
  border-collapse: collapse;
  font-size: 0.86rem;
}

.rich-markdown :deep(th),
.rich-markdown :deep(td) {
  border: 1px solid rgba(var(--line-soft), 0.14);
  padding: 0.45rem 0.55rem;
  vertical-align: top;
}

.rich-markdown :deep(th) {
  background: rgba(var(--bg-muted), 0.72);
  font-weight: 700;
}

.rich-markdown :deep(hr) {
  margin: 0.9rem 0;
  border: 0;
  border-top: 1px solid rgba(var(--line-soft), 0.14);
}

.rich-markdown :deep(code) {
  border-radius: 4px;
  background: rgba(var(--bg-muted), 0.85);
  padding: 0.08rem 0.25rem;
  font-size: 0.88em;
}

.rich-markdown :deep(pre) {
  overflow-x: auto;
  border-radius: var(--radius-soft);
  background: rgb(var(--bg-muted));
  padding: 0.8rem;
}

.rich-markdown :deep(pre code) {
  background: transparent;
  padding: 0;
}

.rich-markdown :deep(.katex-display) {
  overflow-x: auto;
  overflow-y: hidden;
  padding: 0.25rem 0;
}
</style>
