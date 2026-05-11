export type Provider = "openai" | "avalai";

export interface StoredCredentials {
  provider: Provider;
  apiKey: string;
}

export const PROVIDER_LABELS: Record<Provider, string> = {
  openai: "OpenAI",
  avalai: "Avalai",
};

export const PROVIDER_DESCRIPTIONS: Record<Provider, string> = {
  openai: "Uses the OpenAI default endpoint.",
  avalai: "Uses api.avalai.ir/v1 — bring an Avalai key.",
};

const STORAGE_KEY = "adfoundry.credentials";

function isProvider(value: unknown): value is Provider {
  return value === "openai" || value === "avalai";
}

export function getCredentials(): StoredCredentials | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "provider" in parsed &&
      "apiKey" in parsed &&
      isProvider((parsed as { provider: unknown }).provider) &&
      typeof (parsed as { apiKey: unknown }).apiKey === "string" &&
      (parsed as { apiKey: string }).apiKey.length > 0
    ) {
      return parsed as StoredCredentials;
    }
    return null;
  } catch {
    return null;
  }
}

export function saveCredentials(credentials: StoredCredentials): void {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(credentials));
}

export function clearCredentials(): void {
  window.localStorage.removeItem(STORAGE_KEY);
}
