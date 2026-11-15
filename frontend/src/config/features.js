// Review, reading and chat use OpenAI (the deployed demo has no local Ollama).
// Builds with VITE_CLOUD_AI=0 return the UI to the local workflow; the browser tests use that, with mocked local models.
export const CLOUD_AI_ENABLED = import.meta.env.VITE_CLOUD_AI !== "0";
// Multilingual documents remain available independently of a paid provider.
export const DOCUMENT_TRANSLATION_ENABLED = true;
