import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import {
  PROVIDER_DESCRIPTIONS,
  PROVIDER_LABELS,
  type Provider,
  getCredentials,
  saveCredentials,
} from "@/lib/credentials";

const PROVIDERS: Provider[] = ["openai", "avalai"];

export function SetupPage() {
  const navigate = useNavigate();
  const existing = getCredentials();
  const [provider, setProvider] = useState<Provider>(existing?.provider ?? "openai");
  const [apiKey, setApiKey] = useState(existing?.apiKey ?? "");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Setup · AdFoundry";
    return () => {
      document.title = "AdFoundry";
    };
  }, []);

  const handleSave = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = apiKey.trim();
    if (!trimmed) {
      setError("API key is required.");
      return;
    }
    saveCredentials({ provider, apiKey: trimmed });
    navigate("/", { replace: true });
  };

  return (
    <div className="mx-auto max-w-xl py-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5" />
            Configure provider
          </CardTitle>
          <CardDescription>
            Choose where AdFoundry should send LLM requests and paste your own
            API key. The key is stored in your browser and sent with every run
            you start — it never leaves your device except as the LLM call
            itself.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="flex flex-col gap-5">
            <fieldset className="flex flex-col gap-2">
              <Label className="text-sm font-medium">Provider</Label>
              <div className="grid grid-cols-2 gap-2">
                {PROVIDERS.map((p) => (
                  <button
                    type="button"
                    key={p}
                    onClick={() => setProvider(p)}
                    className={cn(
                      "rounded-md border px-3 py-3 text-left transition-colors",
                      provider === p
                        ? "border-primary bg-primary/5 ring-2 ring-primary/30"
                        : "border-border bg-background hover:bg-muted/40",
                    )}
                    aria-pressed={provider === p}
                  >
                    <div className="text-sm font-semibold">
                      {PROVIDER_LABELS[p]}
                    </div>
                    <div className="mt-0.5 text-xs text-muted-foreground">
                      {PROVIDER_DESCRIPTIONS[p]}
                    </div>
                  </button>
                ))}
              </div>
            </fieldset>

            <div className="flex flex-col gap-2">
              <Label htmlFor="api-key" className="text-sm font-medium">
                API key
              </Label>
              <Input
                id="api-key"
                type="password"
                autoComplete="off"
                placeholder="sk-…"
                value={apiKey}
                onChange={(e) => {
                  setApiKey(e.target.value);
                  if (error) setError(null);
                }}
                aria-invalid={error ? true : undefined}
              />
              {error && (
                <p className="text-xs text-destructive">{error}</p>
              )}
            </div>

            <div className="flex justify-end gap-2">
              <Button type="submit">
                {existing ? "Update credentials" : "Save and continue"}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
