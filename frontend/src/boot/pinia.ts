import { defineBoot } from '#q-app';
import { createPinia } from 'pinia';

export default defineBoot(({ app }) => {
  const pinia = createPinia();
  app.use(pinia);
});
