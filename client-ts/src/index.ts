/**
 * Cliente TS para la API privada de la app móvil UTE (Uruguay).
 *
 * Mismo patrón "zero-secret" que el cliente Python: no hay client_id ni
 * client_secret hardcoded. Todos vienen del endpoint público
 * `POST /customersapp/customers/setup` (ver docs/PROTOCOL.md).
 *
 * Pensado para Node 20+ y entornos serverless con `fetch` global.
 *
 * Uso:
 * ```ts
 * const ute = new UteClient();
 * await ute.bootstrap();
 * await ute.login('47543263', 'mi-password');
 * const accounts = await ute.accounts();
 * for (const acc of accounts) {
 *   const sumario = await ute.billingPeriodSummary(acc.accountId);
 *   console.log(`${sumario.currentConsumptionKwh} kWh / $${sumario.currentSpendingUyu}`);
 * }
 * ```
 */

const API_BASE = "https://rocme.ute.com.uy/customersapp";
const USER_AGENT = "Dart/3.7 (dart:io)";

export class UteAuthError extends Error {}
export class UteApiError extends Error {}

export interface OAuthConfig {
  authority: string;
  client: string;
  secret: string;
  scope: string;
  gubUyClient: string;
  gubUySecret: string;
  gubUyAuthEndpoint: string;
  gubUyTokenEndpoint: string;
}

export interface Account {
  accountId: string;
  alias: string;
  address: string;
  icon: string;
  isAuthorized: boolean;
  thirdParty: boolean;
}

export interface Service {
  serviceAgreementId: string;
  servicePointId: string;
  serviceAgreementType: string;
  serviceAgreementStatus: number;
  address: string;
  shortAddress: string;
  city: string;
  department: string;
  zipCode: string;
  tariff: string;
  tariffDescription: string;
  contractedPowerOnPeak: number | null;
  contractedPowerOnValley: number | null;
  contractedPowerOnFlat: number | null;
  voltage: string;
  serviceType: string;
  meterId: string | null;
  amiPresent: boolean;
  amiType: string | null;
}

export type TimeOfUse = "PUNTA" | "LLANO" | "VALLE";

export interface ConsumptionTOU {
  tou: TimeOfUse;
  consumption: number;
  uom: string; // "kWh"
  plan: string;
}

export interface BillingPeriodSummary {
  initialDate: string; // YYYY-MM-DD
  finalDate: string; // YYYY-MM-DD
  currentSpendingUyu: number;
  currentConsumptionKwh: number;
  errorMessage: string | null;
}

interface TokenInternal {
  accessToken: string;
  refreshToken: string;
  expiresAt: number;
  scope: string;
}

export class UteClient {
  private oauth: OAuthConfig | null = null;
  private uniqueId: string | null = null;
  private token: TokenInternal | null = null;
  private refreshing: Promise<void> | null = null;

  constructor(private baseUrl: string = API_BASE) {}

  private requireToken(): TokenInternal {
    if (!this.token) {
      throw new UteAuthError("not authenticated; call bootstrap() and login() first");
    }
    return this.token;
  }

  // ---------------------------------------------------------------
  // Bootstrap zero-secret.
  // ---------------------------------------------------------------
  async bootstrap(): Promise<OAuthConfig> {
    // Pre-fetch del flag (no necesario, pero replica el comportamiento de la app).
    try {
      await fetch(`${this.baseUrl}/flags/SecurityChecksBypass`, {
        headers: this.commonHeaders(),
      });
    } catch {
      // non-fatal
    }

    const r = await fetch(`${this.baseUrl}/customers/setup`, {
      method: "POST",
      headers: {
        ...this.commonHeaders(),
        "content-type": "application/json; charset=utf-8",
      },
      body: JSON.stringify({ registrationId: "", deviceInfo: [] }),
    });
    if (!r.ok) {
      throw new UteApiError(`/customers/setup → ${r.status}: ${await r.text().catch(() => "")}`);
    }
    let body: { uniqueId?: string; oAuthConfiguration?: OAuthConfig };
    try {
      body = (await r.json()) as typeof body;
    } catch (e) {
      throw new UteApiError("invalid JSON in /customers/setup response");
    }
    if (!body.oAuthConfiguration || !body.uniqueId) {
      throw new UteApiError(`unexpected /customers/setup shape: ${JSON.stringify(body).slice(0, 200)}`);
    }
    this.oauth = body.oAuthConfiguration;
    this.uniqueId = body.uniqueId;
    return this.oauth;
  }

  // ---------------------------------------------------------------
  // Login ROPC.
  // ---------------------------------------------------------------
  async login(username: string, password: string): Promise<void> {
    if (!this.oauth) throw new Error("call bootstrap() first");
    await this.oauthToken({
      grant_type: "password",
      username,
      password,
    });
    if (this.uniqueId) {
      await this.post(`${this.baseUrl}/customers/loggedin`, {
        uniqueId: this.uniqueId,
      });
    }
  }

  private async oauthToken(extra: Record<string, string>): Promise<void> {
    if (!this.oauth) {
      throw new UteAuthError("call bootstrap() before requesting a token");
    }
    const basic = btoa(`${this.oauth.client}:${this.oauth.secret}`);
    const params = new URLSearchParams(extra);
    const r = await fetch(`${this.oauth.authority}/connect/token`, {
      method: "POST",
      headers: {
        ...this.commonHeaders(),
        authorization: `Basic ${basic}`,
        "content-type": "application/x-www-form-urlencoded; charset=utf-8",
      },
      body: params.toString(),
    });
    if (r.status === 400 || r.status === 401) {
      let err: { error?: string; error_description?: string } = {};
      try {
        err = (await r.json()) as typeof err;
      } catch {
        err = { error_description: (await r.text()).slice(0, 200) };
      }
      throw new UteAuthError(`${err.error || r.status}: ${err.error_description || ""}`);
    }
    if (!r.ok) {
      throw new UteApiError(`/connect/token → ${r.status}`);
    }
    let tok: {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
      scope?: string;
    };
    try {
      tok = (await r.json()) as typeof tok;
    } catch {
      throw new UteApiError("invalid JSON in /connect/token");
    }
    if (!tok.access_token || typeof tok.expires_in !== "number") {
      throw new UteApiError("unexpected /connect/token response shape");
    }
    this.token = {
      accessToken: tok.access_token,
      refreshToken: tok.refresh_token || "",
      expiresAt: Date.now() + tok.expires_in * 1000,
      scope: tok.scope || "",
    };
  }

  private async refreshIfNeeded(): Promise<void> {
    if (this.token && this.token.expiresAt > Date.now() + 30_000) return;
    // Coalesce refresh requests concurrentes; el primero rota el refresh_token
    // y los demás esperan al mismo `Promise<void>`.
    if (this.refreshing) {
      await this.refreshing;
      return;
    }
    this.refreshing = (async () => {
      try {
        if (this.token?.refreshToken) {
          try {
            await this.oauthToken({
              grant_type: "refresh_token",
              refresh_token: this.token.refreshToken,
            });
            return;
          } catch (e) {
            if (!(e instanceof UteAuthError)) throw e;
            this.token = null;
          }
        }
        throw new UteAuthError("token expired and refresh invalid — re-login");
      } finally {
        this.refreshing = null;
      }
    })();
    await this.refreshing;
  }

  // ---------------------------------------------------------------
  // HTTP helpers.
  // ---------------------------------------------------------------
  private commonHeaders(): HeadersInit {
    return {
      "user-agent": USER_AGENT,
      "accept-encoding": "gzip",
    };
  }

  private async authedFetch(url: string, init?: RequestInit): Promise<Response> {
    await this.refreshIfNeeded();
    const r = await fetch(url, {
      ...init,
      headers: {
        ...this.commonHeaders(),
        ...(init?.headers ?? {}),
        authorization: `Bearer ${this.requireToken().accessToken}`,
      },
    });
    if (r.status === 401 && this.token) {
      // Forzar refresh sin descartar el refresh_token.
      this.token.expiresAt = 0;
      await this.refreshIfNeeded();
      return fetch(url, {
        ...init,
        headers: {
          ...this.commonHeaders(),
          ...(init?.headers ?? {}),
          authorization: `Bearer ${this.requireToken().accessToken}`,
        },
      });
    }
    return r;
  }

  private async get<T>(url: string): Promise<T> {
    const r = await this.authedFetch(url);
    if (!r.ok)
      throw new UteApiError(`GET ${url} → ${r.status}: ${await r.text()}`);
    return r.json() as Promise<T>;
  }

  private async post<T>(url: string, body: unknown): Promise<T> {
    const r = await this.authedFetch(url, {
      method: "POST",
      headers: { "content-type": "application/json; charset=utf-8" },
      body: JSON.stringify(body),
    });
    if (!r.ok)
      throw new UteApiError(`POST ${url} → ${r.status}: ${await r.text()}`);
    const text = await r.text();
    return (text ? JSON.parse(text) : null) as T;
  }

  // ---------------------------------------------------------------
  // Endpoints.
  // ---------------------------------------------------------------
  async accounts(): Promise<Account[]> {
    return this.get<Account[]>(`${this.baseUrl}/accounts`);
  }

  async services(accountId: string): Promise<Service[]> {
    return this.get<Service[]>(`${this.baseUrl}/accounts/${accountId}/services`);
  }

  async consumptionByTou(
    servicePointId: string,
    plan: string = "TRIPLERES17",
    dateFrom: string = "",
    dateTo: string = "",
  ): Promise<ConsumptionTOU[]> {
    return this.get<ConsumptionTOU[]>(
      `${this.baseUrl}/accounts/${servicePointId}/calculateConsumptionForPlan/${plan}/${dateFrom}/${dateTo}`,
    );
  }

  async totalDebt(accountId: string): Promise<number> {
    const r = await this.authedFetch(`${this.baseUrl}/invoices/totalDebt/${accountId}`);
    const text = (await r.text()).trim();
    return text === "" ? 0 : Number(text);
  }

  async billingPeriodSummary(accountId: string): Promise<BillingPeriodSummary> {
    const raw = await this.post<{
      initialDate: string;
      finalDate: string;
      currentSpending: number;
      currentConsumption: number;
      errorMessage: string | null;
    }>(`${this.baseUrl}/accounts/consumption/simulation`, { accountId });
    return {
      initialDate: raw.initialDate.slice(0, 10),
      finalDate: raw.finalDate.slice(0, 10),
      currentSpendingUyu: raw.currentSpending,
      currentConsumptionKwh: raw.currentConsumption,
      errorMessage: raw.errorMessage,
    };
  }

  async supplyStatus(
    accountId: string,
    serviceAgreementId: string,
    servicePointId: string,
  ): Promise<{
    isInterrupted: boolean;
    timestamp: string;
    supplyStatus: unknown;
    supplyStatusMessages: unknown[];
  }> {
    return this.get(
      `${this.baseUrl}/accounts/${accountId}/services/${serviceAgreementId}/${servicePointId}/status`,
    );
  }

  async messagesUnread(): Promise<number> {
    const r = await this.authedFetch(`${this.baseUrl}/messages/unread`);
    const text = (await r.text()).trim();
    return text === "" ? 0 : Number(text);
  }
}

export default UteClient;
