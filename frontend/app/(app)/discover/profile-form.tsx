"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { ApiRequestError } from "@/lib/api-types";
import { getProfile, updateProfile, type Profile, type ProfileLevel } from "@/lib/discovery-api";

const LEVEL_OPTIONS: ProfileLevel[] = ["beginner", "intermediate", "advanced"];

function errorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) return error.message;
  if (error instanceof Error) return error.message;
  return "Could not load profile.";
}

function parseCommaList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

/** Recommendation targeting profile — interests/level/goals, per
 * `GET /discover/profile` / `PUT /discover/profile`. */
export function ProfileForm() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [interests, setInterests] = useState("");
  const [level, setLevel] = useState<ProfileLevel>("beginner");
  const [goals, setGoals] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getProfile()
      .then((loaded) => {
        setProfile(loaded);
        setInterests(loaded.interests.join(", "));
        setLevel(loaded.level);
        setGoals(loaded.goals.join(", "));
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  async function handleSave(): Promise<void> {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const next = await updateProfile({
        interests: parseCommaList(interests),
        level,
        goals: parseCommaList(goals),
      });
      setProfile(next);
      setSaved(true);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <h2 className="text-h4 font-display font-semibold text-foreground">Recommendation profile</h2>

      {error && (
        <p role="alert" className="text-body text-mismatch">
          {error}
        </p>
      )}
      {!profile && !error && <p className="text-body text-muted-foreground">Loading…</p>}

      {(profile || error === null) && (
        <>
          <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="profile-interests">
            Interests (comma-separated)
            <input
              id="profile-interests"
              type="text"
              value={interests}
              onChange={(event) => setInterests(event.target.value)}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
            />
          </label>

          <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="profile-level">
            Level
            <select
              id="profile-level"
              value={level}
              onChange={(event) => setLevel(event.target.value as ProfileLevel)}
              className="rounded-md border border-input bg-background px-2 py-1.5 text-body text-foreground"
            >
              {LEVEL_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-ui-label text-foreground" htmlFor="profile-goals">
            Goals (comma-separated)
            <input
              id="profile-goals"
              type="text"
              value={goals}
              onChange={(event) => setGoals(event.target.value)}
              className="rounded-md border border-input bg-background px-3 py-1.5 text-body text-foreground"
            />
          </label>

          <div className="flex items-center gap-2">
            <Button type="button" onClick={() => void handleSave()} disabled={saving}>
              {saving ? "Saving…" : "Save profile"}
            </Button>
            {saved && <span className="text-caption text-verified">Saved.</span>}
          </div>
        </>
      )}
    </div>
  );
}
