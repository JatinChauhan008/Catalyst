import type { Catalog, ConvertRequest, Envelope, JobSummary } from "./types";

async function errorText(response: Response): Promise<string> {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
  } catch {
    return `${response.status} ${response.statusText}`;
  }
}

export async function fetchCatalog(): Promise<Catalog> {
  const response = await fetch("/api/catalog");
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}

export async function convertFile(file: File, request: ConvertRequest): Promise<Envelope> {
  const body = new FormData();
  body.append("file", file, file.name);
  body.append("options", JSON.stringify(request));
  const response = await fetch("/api/convert", { method: "POST", body });
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}

export async function fetchJobs(limit = 50): Promise<JobSummary[]> {
  const response = await fetch(`/api/jobs?limit=${limit}`);
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}

export async function fetchJob(jobId: string): Promise<Envelope> {
  const response = await fetch(`/api/jobs/${jobId}`);
  if (!response.ok) throw new Error(await errorText(response));
  return response.json();
}
