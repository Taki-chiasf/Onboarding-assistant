"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { User } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export type Persona = {
  sub: string;
  email: string;
  dept: string;
  role: string;
};

function personaLabel(persona: Persona): string {
  if (persona.role === "admin") return "HR admin";
  if (persona.dept === "Engineering") return "Engineering new hire";
  return `${persona.dept} employee`;
}

export function PersonaPicker() {
  const router = useRouter();
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/auth/personas")
      .then((res) => {
        if (!res.ok) throw new Error("could not load personas");
        return res.json();
      })
      .then(setPersonas)
      .catch(() => setError("Could not load demo personas."));
  }, []);

  async function select(persona: Persona) {
    setLoading(persona.sub);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(persona),
    });
    if (!res.ok) {
      setError("Sign-in failed. Is the backend reachable?");
      setLoading(null);
      return;
    }
    router.push("/");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-semibold tracking-tight">Onboarding Assistant</h1>
          <p className="mt-2 text-muted-foreground">
            Pick a demo identity to explore the assistant.
          </p>
        </div>

        {error && (
          <p className="mb-4 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-3">
          {personas.map((persona) => (
            <Card key={persona.sub} className="flex flex-col">
              <CardHeader>
                <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-full bg-muted">
                  <User className="h-5 w-5" />
                </div>
                <CardTitle>{personaLabel(persona)}</CardTitle>
                <CardDescription>{persona.dept}</CardDescription>
              </CardHeader>
              <CardContent className="mt-auto">
                <Button
                  className="w-full"
                  onClick={() => select(persona)}
                  disabled={loading !== null}
                >
                  {loading === persona.sub ? "Signing in…" : "Continue"}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>

        {!error && personas.length === 0 && (
          <p className="mt-8 text-center text-sm text-muted-foreground">
            Loading demo personas…
          </p>
        )}
      </div>
    </div>
  );
}
