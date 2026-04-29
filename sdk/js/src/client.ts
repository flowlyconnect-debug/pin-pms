import type { ApiResponse } from "./types";

export class PMSClient {
  private apiKey: string;
  private baseUrl: string;

  constructor(apiKey: string, baseUrl = "http://127.0.0.1:5000") {
    this.apiKey = apiKey;
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  async reservationsList(page = 1, perPage = 20) {
    return this.request(`/api/v1/reservations?page=${page}&per_page=${perPage}`);
  }

  async reservationsCreate(payload: Record<string, unknown>) {
    return this.request("/api/v1/reservations", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  async reservationsGet(id: number) {
    return this.request(`/api/v1/reservations/${id}`);
  }

  async reservationsCancel(id: number) {
    return this.request(`/api/v1/reservations/${id}/cancel`, { method: "PATCH" });
  }

  private async request(path: string, init: RequestInit = {}) {
    const response = await fetch(`${this.baseUrl}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.apiKey}`,
        ...(init.headers || {}),
      },
    });
    const payload = (await response.json()) as ApiResponse<unknown>;
    if (!response.ok) {
      throw new Error(payload.error?.message || "API request failed");
    }
    return payload.data;
  }
}
